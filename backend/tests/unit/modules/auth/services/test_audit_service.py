from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.auth.repository.audit_event_repository import AuditEventRepository
from aep.modules.auth.services.audit_service import AuditService


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
def audit_service(session) -> AuditService:
    return AuditService(AuditEventRepository(session))


async def test_record_event_requires_an_actor(audit_service: AuditService) -> None:
    with pytest.raises(ValueError, match="actor"):
        await audit_service.record_event(event_type="x", entity_type="project", entity_id=uuid4())


async def test_record_and_get_event(audit_service: AuditService) -> None:
    actor_id = uuid4()
    entity_id = uuid4()

    recorded = await audit_service.record_event(
        event_type="project.created",
        entity_type="project",
        entity_id=entity_id,
        actor_user_id=actor_id,
        payload={"name": "AEP"},
    )

    fetched = await audit_service.get_event(recorded.id)
    assert fetched is not None
    assert fetched.event_type == "project.created"
    assert fetched.payload == {"name": "AEP"}


async def test_list_events_filters(audit_service: AuditService) -> None:
    actor_id = uuid4()
    await audit_service.record_event(
        event_type="a", entity_type="project", entity_id=uuid4(), actor_user_id=actor_id
    )
    await audit_service.record_event(
        event_type="b", entity_type="feature", entity_id=uuid4(), actor_user_id=actor_id
    )

    events, _, _ = await audit_service.list_events(entity_type="project")
    assert len(events) == 1
    assert events[0].event_type == "a"
