from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.task_memory.domain.models import (
    ExecutionHistoryEntry,
    Task,
    TaskStatus,
    TaskType,
)
from aep.modules.task_memory.repository.execution_history_repository import (
    ExecutionHistoryRepository,
)
from aep.modules.task_memory.repository.task_repository import TaskRepository


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
async def task(session):
    return await TaskRepository(session).add(
        Task(id=uuid4(), feature_id=uuid4(), title="A", task_type=TaskType.CODE)
    )


async def test_add_requires_an_actor(session, task) -> None:
    repository = ExecutionHistoryRepository(session)
    user_id = uuid4()

    entry = await repository.add(
        ExecutionHistoryEntry(
            id=uuid4(),
            task_id=task.id,
            from_status=TaskStatus.PENDING,
            to_status=TaskStatus.READY,
            changed_by_user_id=user_id,
        )
    )

    assert entry.from_status == TaskStatus.PENDING
    assert entry.to_status == TaskStatus.READY
    assert entry.changed_by_user_id == user_id


async def test_list_for_task_is_newest_first_and_paginates(session, task) -> None:
    repository = ExecutionHistoryRepository(session)
    user_id = uuid4()
    transitions = [
        (None, TaskStatus.PENDING),
        (TaskStatus.PENDING, TaskStatus.READY),
        (TaskStatus.READY, TaskStatus.RUNNING),
        (TaskStatus.RUNNING, TaskStatus.EVALUATING),
        (TaskStatus.EVALUATING, TaskStatus.AWAITING_APPROVAL),
    ]
    for from_status, to_status in transitions:
        await repository.add(
            ExecutionHistoryEntry(
                id=uuid4(),
                task_id=task.id,
                from_status=from_status,
                to_status=to_status,
                changed_by_user_id=user_id,
            )
        )

    first_page, cursor, has_more = await repository.list_for_task(task.id, limit=2)
    assert len(first_page) == 2
    assert has_more is True
    assert first_page[0].to_status == TaskStatus.AWAITING_APPROVAL
    assert first_page[1].to_status == TaskStatus.EVALUATING

    second_page, cursor2, _has_more2 = await repository.list_for_task(task.id, limit=2, cursor=cursor)
    assert len(second_page) == 2
    assert second_page[0].to_status == TaskStatus.RUNNING
    assert second_page[1].to_status == TaskStatus.READY

    third_page, cursor3, has_more3 = await repository.list_for_task(task.id, limit=2, cursor=cursor2)
    assert len(third_page) == 1
    assert third_page[0].to_status == TaskStatus.PENDING
    assert has_more3 is False
    assert cursor3 is None
