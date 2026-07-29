from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.auth.domain.models import AuditEvent, User
from aep.modules.auth.repository.audit_event_repository import AuditEventRepository
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


async def test_add_and_get_by_id_round_trips_with_json_payload(session, user) -> None:
    repository = AuditEventRepository(session)
    entity_id = uuid4()

    created = await repository.add(
        AuditEvent(
            id=uuid4(),
            event_type="project.created",
            entity_type="project",
            entity_id=entity_id,
            actor_user_id=user.id,
            payload={"slug": "aep", "name": "AEP"},
        )
    )

    fetched = await repository.get_by_id(created.id)
    assert fetched is not None
    assert fetched.payload == {"slug": "aep", "name": "AEP"}
    assert fetched.actor_user_id == user.id
    assert fetched.actor_agent_id is None


async def test_list_filters_by_entity_and_event_type(session, user) -> None:
    repository = AuditEventRepository(session)
    project_id = uuid4()
    await repository.add(
        AuditEvent(
            id=uuid4(),
            event_type="project.created",
            entity_type="project",
            entity_id=project_id,
            actor_user_id=user.id,
        )
    )
    await repository.add(
        AuditEvent(
            id=uuid4(),
            event_type="project.archived",
            entity_type="project",
            entity_id=project_id,
            actor_user_id=user.id,
        )
    )
    await repository.add(
        AuditEvent(
            id=uuid4(),
            event_type="feature.created",
            entity_type="feature",
            entity_id=uuid4(),
            actor_user_id=user.id,
        )
    )

    for_project, _, _ = await repository.list(entity_type="project", entity_id=project_id)
    assert len(for_project) == 2

    only_created, _, _ = await repository.list(event_type="project.created")
    assert len(only_created) == 1


async def test_list_paginates_newest_first(session, user) -> None:
    repository = AuditEventRepository(session)
    for i in range(3):
        await repository.add(
            AuditEvent(
                id=uuid4(),
                event_type=f"event.{i}",
                entity_type="project",
                entity_id=uuid4(),
                actor_user_id=user.id,
            )
        )

    first_page, cursor, has_more = await repository.list(limit=2)
    assert len(first_page) == 2
    assert has_more is True
    assert first_page[0].event_type == "event.2"

    second_page, _, has_more2 = await repository.list(limit=2, cursor=cursor)
    assert len(second_page) == 1
    assert second_page[0].event_type == "event.0"
    assert has_more2 is False
