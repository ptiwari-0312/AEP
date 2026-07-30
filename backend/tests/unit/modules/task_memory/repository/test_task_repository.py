from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.task_memory.domain.models import Task, TaskStatus, TaskType
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
async def repository():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield TaskRepository(session)


async def test_add_and_get_by_id_round_trips(repository: TaskRepository) -> None:
    feature_id = uuid4()
    task = Task(id=uuid4(), feature_id=feature_id, title="Write endpoint", task_type=TaskType.CODE)

    created = await repository.add(task)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.title == "Write endpoint"
    assert fetched.task_type == TaskType.CODE
    assert fetched.status == TaskStatus.PENDING


async def test_list_for_feature_filters_by_status_and_type(repository: TaskRepository) -> None:
    feature_id = uuid4()
    await repository.add(Task(id=uuid4(), feature_id=feature_id, title="A", task_type=TaskType.CODE))
    test_task = await repository.add(
        Task(id=uuid4(), feature_id=feature_id, title="B", task_type=TaskType.TEST)
    )
    await repository.add(Task(id=uuid4(), feature_id=uuid4(), title="Other feature", task_type=TaskType.CODE))

    tasks, _, _ = await repository.list_for_feature(feature_id)
    assert len(tasks) == 2

    only_test, _, _ = await repository.list_for_feature(feature_id, task_type=TaskType.TEST)
    assert len(only_test) == 1
    assert only_test[0].id == test_task.id


async def test_list_for_feature_paginates_with_cursor(repository: TaskRepository) -> None:
    feature_id = uuid4()
    for i in range(5):
        await repository.add(
            Task(id=uuid4(), feature_id=feature_id, title=f"Task {i}", task_type=TaskType.CODE)
        )

    first_page, cursor, has_more = await repository.list_for_feature(feature_id, limit=2)
    assert len(first_page) == 2
    assert has_more is True
    assert cursor is not None

    second_page, cursor2, has_more2 = await repository.list_for_feature(
        feature_id, limit=2, cursor=cursor
    )
    assert len(second_page) == 2
    assert has_more2 is True
    assert {t.title for t in first_page} != {t.title for t in second_page}

    third_page, cursor3, has_more3 = await repository.list_for_feature(
        feature_id, limit=2, cursor=cursor2
    )
    assert len(third_page) == 1
    assert has_more3 is False
    assert cursor3 is None


async def test_update_persists_changes(repository: TaskRepository) -> None:
    task = await repository.add(
        Task(id=uuid4(), feature_id=uuid4(), title="Original", task_type=TaskType.CODE)
    )

    task.title = "Renamed"
    task.priority = 5
    task.status = TaskStatus.READY
    updated = await repository.update(task)

    assert updated.title == "Renamed"
    assert updated.priority == 5
    assert updated.status == TaskStatus.READY


async def test_count_by_status_is_global_not_scoped_to_a_feature(repository: TaskRepository) -> None:
    await repository.add(Task(id=uuid4(), feature_id=uuid4(), title="A", task_type=TaskType.CODE))
    task_b = await repository.add(
        Task(id=uuid4(), feature_id=uuid4(), title="B", task_type=TaskType.CODE)
    )
    task_b.status = TaskStatus.READY
    await repository.update(task_b)

    assert await repository.count_by_status(TaskStatus.PENDING) == 1
    assert await repository.count_by_status(TaskStatus.READY) == 1
    assert await repository.count_by_status(TaskStatus.MERGED) == 0
