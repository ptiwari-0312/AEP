from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory, utcnow
from aep.modules.auth.domain.models import RefreshToken, User
from aep.modules.auth.repository.refresh_token_repository import RefreshTokenRepository
from aep.modules.auth.repository.user_repository import UserRepository


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


@pytest.fixture
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
async def user(session) -> User:
    return await UserRepository(session).add(
        User(id=uuid4(), email="a@example.com", display_name="A", auth_provider="github", auth_subject="1")
    )


async def test_add_and_get_by_hash_round_trips(session, user) -> None:
    repository = RefreshTokenRepository(session)

    created = await repository.add(
        RefreshToken(
            id=uuid4(), user_id=user.id, token_hash="abc123", expires_at=utcnow() + timedelta(days=30)
        )
    )

    fetched = await repository.get_by_hash("abc123")
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.revoked_at is None

    assert await repository.get_by_hash("does-not-exist") is None


async def test_revoke_sets_revoked_at(session, user) -> None:
    repository = RefreshTokenRepository(session)
    token = await repository.add(
        RefreshToken(
            id=uuid4(), user_id=user.id, token_hash="xyz", expires_at=utcnow() + timedelta(days=30)
        )
    )

    await repository.revoke(token.id)

    reloaded = await repository.get_by_hash("xyz")
    assert reloaded is not None
    assert reloaded.revoked_at is not None


async def test_revoke_is_idempotent(session, user) -> None:
    repository = RefreshTokenRepository(session)
    token = await repository.add(
        RefreshToken(
            id=uuid4(), user_id=user.id, token_hash="idempotent", expires_at=utcnow() + timedelta(days=30)
        )
    )

    await repository.revoke(token.id)
    first_revoked_at = (await repository.get_by_hash("idempotent")).revoked_at
    await repository.revoke(token.id)
    second_revoked_at = (await repository.get_by_hash("idempotent")).revoked_at

    assert first_revoked_at == second_revoked_at
