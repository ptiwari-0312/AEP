from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.core.security import decode_access_token
from aep.modules.auth.domain.errors import (
    InvalidRefreshTokenError,
    UnsupportedOAuthProviderError,
)
from aep.modules.auth.repository.audit_event_repository import AuditEventRepository
from aep.modules.auth.repository.refresh_token_repository import RefreshTokenRepository
from aep.modules.auth.repository.role_repository import RoleRepository
from aep.modules.auth.repository.user_repository import UserRepository
from aep.modules.auth.services.audit_service import AuditService
from aep.modules.auth.services.auth_service import AuthService
from aep.modules.auth.services.oauth import OAuthIdentity


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEP_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


class FakeOAuthProvider:
    provider_name = "github"

    def __init__(self, identity: OAuthIdentity) -> None:
        self._identity = identity
        self.exchanged_codes: list[str] = []

    async def exchange_code(self, code: str) -> OAuthIdentity:
        self.exchanged_codes.append(code)
        return self._identity


@pytest.fixture
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
def fake_provider() -> FakeOAuthProvider:
    return FakeOAuthProvider(
        OAuthIdentity(provider="github", subject="42", email="a@example.com", display_name="A")
    )


@pytest.fixture
def auth_service(session, fake_provider) -> AuthService:
    return AuthService(
        UserRepository(session),
        RoleRepository(session),
        RefreshTokenRepository(session),
        {"github": fake_provider},
        AuditService(AuditEventRepository(session)),
    )


async def test_login_creates_a_new_user_on_first_login(auth_service: AuthService) -> None:
    result = await auth_service.login(provider="github", code="code-123")

    assert result.user.email == "a@example.com"
    assert result.user.auth_provider == "github"
    assert result.user.auth_subject == "42"
    assert result.expires_in > 0
    decoded = decode_access_token(result.access_token)
    assert decoded.user_id == result.user.id


async def test_login_reuses_existing_user_on_second_login(auth_service: AuthService) -> None:
    first = await auth_service.login(provider="github", code="code-1")
    second = await auth_service.login(provider="github", code="code-2")

    assert first.user.id == second.user.id


async def test_login_raises_for_unsupported_provider(auth_service: AuthService) -> None:
    with pytest.raises(UnsupportedOAuthProviderError):
        await auth_service.login(provider="google", code="anything")


async def test_refresh_rotates_the_token_and_old_one_stops_working(auth_service: AuthService) -> None:
    login_result = await auth_service.login(provider="github", code="code-1")

    refresh_result = await auth_service.refresh(refresh_token=login_result.refresh_token)
    # Not asserting access_token != login_result.access_token: two tokens issued for the same
    # user/roles within the same second have identical `iat`/`exp` claims (second-granularity),
    # so they're legitimately the same JWT string — that's not a rotation guarantee to test.
    # The refresh token rotating (and the old one dying) is the actual security property.
    assert decode_access_token(refresh_result.access_token).user_id == login_result.user.id
    assert refresh_result.refresh_token != login_result.refresh_token

    with pytest.raises(InvalidRefreshTokenError):
        await auth_service.refresh(refresh_token=login_result.refresh_token)


async def test_refresh_rejects_unknown_token(auth_service: AuthService) -> None:
    with pytest.raises(InvalidRefreshTokenError):
        await auth_service.refresh(refresh_token="not-a-real-token")


async def test_logout_revokes_the_refresh_token(auth_service: AuthService) -> None:
    login_result = await auth_service.login(provider="github", code="code-1")

    await auth_service.logout(refresh_token=login_result.refresh_token)

    with pytest.raises(InvalidRefreshTokenError):
        await auth_service.refresh(refresh_token=login_result.refresh_token)


async def test_logout_is_a_no_op_for_an_unknown_token(auth_service: AuthService) -> None:
    await auth_service.logout(refresh_token="never-existed")  # should not raise


async def test_login_records_an_audit_event(session, auth_service: AuthService) -> None:
    result = await auth_service.login(provider="github", code="code-1")

    events, _, _ = await AuditEventRepository(session).list(entity_type="user", entity_id=result.user.id)
    assert len(events) == 1
    assert events[0].event_type == "user.login"
    assert events[0].actor_user_id == result.user.id
    assert events[0].payload == {"provider": "github"}


async def test_login_includes_granted_roles_in_access_token(session, auth_service: AuthService, fake_provider) -> None:
    result = await auth_service.login(provider="github", code="code-1")
    role_repository = RoleRepository(session)
    from aep.modules.auth.repository.models import RoleModel

    role = RoleModel(id=uuid4(), name="engineer")
    session.add(role)
    await session.flush()
    await role_repository.grant(result.user.id, role.id, granted_by=None)

    second_login = await auth_service.login(provider="github", code="code-2")

    decoded = decode_access_token(second_login.access_token)
    assert decoded.roles == ["engineer"]
