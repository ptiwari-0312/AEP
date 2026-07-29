from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.auth.domain.models import User, UserStatus
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
async def repository():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield UserRepository(session)


def _user(**overrides) -> User:
    defaults = {
        "id": uuid4(),
        "email": "a@example.com",
        "display_name": "A",
        "auth_provider": "github",
        "auth_subject": "123",
    }
    defaults.update(overrides)
    return User(**defaults)


async def test_add_and_get_by_id_round_trips(repository: UserRepository) -> None:
    created = await repository.add(_user())

    fetched = await repository.get_by_id(created.id)
    assert fetched is not None
    assert fetched.email == "a@example.com"
    assert fetched.status == UserStatus.ACTIVE


async def test_get_by_provider_subject_finds_existing_user(repository: UserRepository) -> None:
    await repository.add(_user(auth_provider="github", auth_subject="999"))

    found = await repository.get_by_provider_subject("github", "999")
    assert found is not None

    assert await repository.get_by_provider_subject("github", "does-not-exist") is None


async def test_list_filters_by_status_and_email(repository: UserRepository) -> None:
    await repository.add(_user(email="active@example.com", auth_subject="1"))
    disabled = await repository.add(
        _user(email="disabled@example.com", auth_subject="2", status=UserStatus.DISABLED)
    )

    active_users, total = await repository.list(status=UserStatus.ACTIVE)
    assert total == 1
    assert active_users[0].email == "active@example.com"

    by_email, total_by_email = await repository.list(email="disabled@example.com")
    assert total_by_email == 1
    assert by_email[0].id == disabled.id


async def test_update_persists_display_name_and_status(repository: UserRepository) -> None:
    user = await repository.add(_user())

    user.display_name = "Renamed"
    user.status = UserStatus.DISABLED
    updated = await repository.update(user)

    assert updated.display_name == "Renamed"
    assert updated.status == UserStatus.DISABLED
