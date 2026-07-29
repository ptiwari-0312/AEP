from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.auth.domain.models import User
from aep.modules.auth.repository.models import RoleModel
from aep.modules.auth.repository.role_repository import RoleRepository
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


@pytest.fixture
async def engineer_role(session) -> RoleModel:
    role = RoleModel(id=uuid4(), name="engineer", description="Creates/modifies work")
    session.add(role)
    await session.flush()
    await session.refresh(role)
    return role


async def test_list_all_and_get_by_name(session, engineer_role) -> None:
    repository = RoleRepository(session)

    roles = await repository.list_all()
    assert [r.name for r in roles] == ["engineer"]

    found = await repository.get_by_name("engineer")
    assert found is not None
    assert found.id == engineer_role.id

    assert await repository.get_by_name("does-not-exist") is None


async def test_grant_and_list_role_names_for_user(session, user, engineer_role) -> None:
    repository = RoleRepository(session)

    granted = await repository.grant(user.id, engineer_role.id, granted_by=None)
    assert granted.user_id == user.id
    assert granted.role_id == engineer_role.id
    assert granted.granted_at is not None

    role_names = await repository.list_role_names_for_user(user.id)
    assert role_names == ["engineer"]

    assert await repository.has_role(user.id, engineer_role.id) is True


async def test_revoke_removes_the_grant(session, user, engineer_role) -> None:
    repository = RoleRepository(session)
    await repository.grant(user.id, engineer_role.id, granted_by=None)

    await repository.revoke(user.id, engineer_role.id)

    assert await repository.has_role(user.id, engineer_role.id) is False
    assert await repository.list_role_names_for_user(user.id) == []


async def test_revoke_is_a_no_op_when_not_granted(session, user, engineer_role) -> None:
    repository = RoleRepository(session)

    await repository.revoke(user.id, engineer_role.id)  # should not raise

    assert await repository.has_role(user.id, engineer_role.id) is False
