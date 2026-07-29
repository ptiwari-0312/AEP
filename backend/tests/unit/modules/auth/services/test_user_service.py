from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.auth.domain.errors import (
    RoleAlreadyGrantedError,
    RoleNotGrantedError,
    UserNotFoundError,
)
from aep.modules.auth.domain.models import User, UserStatus
from aep.modules.auth.repository.models import RoleModel
from aep.modules.auth.repository.role_repository import RoleRepository
from aep.modules.auth.repository.user_repository import UserRepository
from aep.modules.auth.services.user_service import UserService


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
def user_service(session) -> UserService:
    return UserService(UserRepository(session), RoleRepository(session))


@pytest.fixture
async def user(session) -> User:
    return await UserRepository(session).add(
        User(id=uuid4(), email="a@example.com", display_name="A", auth_provider="github", auth_subject="1")
    )


@pytest.fixture
async def engineer_role(session) -> RoleModel:
    role = RoleModel(id=uuid4(), name="engineer")
    session.add(role)
    await session.flush()
    await session.refresh(role)
    return role


async def test_get_user_raises_not_found(user_service: UserService) -> None:
    with pytest.raises(UserNotFoundError):
        await user_service.get_user(uuid4())


async def test_get_user_includes_resolved_roles(user_service: UserService, user, engineer_role) -> None:
    await user_service.grant_role(user.id, role_id=engineer_role.id)

    fetched = await user_service.get_user(user.id)

    assert fetched.roles == ["engineer"]


async def test_update_user_changes_display_name_and_status(user_service: UserService, user) -> None:
    updated = await user_service.update_user(user.id, display_name="Renamed", status=UserStatus.DISABLED)

    assert updated.display_name == "Renamed"
    assert updated.status == UserStatus.DISABLED


async def test_grant_role_rejects_duplicate_grant(user_service: UserService, user, engineer_role) -> None:
    await user_service.grant_role(user.id, role_id=engineer_role.id)

    with pytest.raises(RoleAlreadyGrantedError):
        await user_service.grant_role(user.id, role_id=engineer_role.id)


async def test_revoke_role_rejects_when_not_granted(user_service: UserService, user, engineer_role) -> None:
    with pytest.raises(RoleNotGrantedError):
        await user_service.revoke_role(user.id, engineer_role.id)


async def test_grant_then_revoke_role(user_service: UserService, user, engineer_role) -> None:
    await user_service.grant_role(user.id, role_id=engineer_role.id)
    await user_service.revoke_role(user.id, engineer_role.id)

    fetched = await user_service.get_user(user.id)
    assert fetched.roles == []


async def test_list_users_respects_status_filter(user_service: UserService, user) -> None:
    await user_service.update_user(user.id, status=UserStatus.DISABLED)

    _active, active_total = await user_service.list_users(status=UserStatus.ACTIVE)
    disabled, disabled_total = await user_service.list_users(status=UserStatus.DISABLED)

    assert active_total == 0
    assert disabled_total == 1
    assert disabled[0].id == user.id
