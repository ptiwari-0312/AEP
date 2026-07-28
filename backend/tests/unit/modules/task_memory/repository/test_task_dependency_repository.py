from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.task_memory.domain.models import (
    DependencyType,
    Task,
    TaskDependency,
    TaskType,
)
from aep.modules.task_memory.repository.task_dependency_repository import (
    TaskDependencyRepository,
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
async def two_tasks(session):
    tasks = TaskRepository(session)
    feature_id = uuid4()
    a = await tasks.add(Task(id=uuid4(), feature_id=feature_id, title="A", task_type=TaskType.CODE))
    b = await tasks.add(Task(id=uuid4(), feature_id=feature_id, title="B", task_type=TaskType.CODE))
    return a, b


async def test_add_and_get_by_id_round_trips(session, two_tasks) -> None:
    task_a, task_b = two_tasks
    repository = TaskDependencyRepository(session)

    created = await repository.add(
        TaskDependency(id=uuid4(), task_id=task_a.id, depends_on_task_id=task_b.id)
    )
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.task_id == task_a.id
    assert fetched.depends_on_task_id == task_b.id
    assert fetched.dependency_type == DependencyType.BLOCKS


async def test_list_for_task_returns_only_edges_where_task_is_dependent(session, two_tasks) -> None:
    task_a, task_b = two_tasks
    repository = TaskDependencyRepository(session)
    await repository.add(TaskDependency(id=uuid4(), task_id=task_a.id, depends_on_task_id=task_b.id))

    a_deps = await repository.list_for_task(task_a.id)
    b_deps = await repository.list_for_task(task_b.id)

    assert len(a_deps) == 1
    assert a_deps[0].depends_on_task_id == task_b.id
    assert b_deps == []


async def test_exists_detects_existing_edge(session, two_tasks) -> None:
    task_a, task_b = two_tasks
    repository = TaskDependencyRepository(session)
    await repository.add(TaskDependency(id=uuid4(), task_id=task_a.id, depends_on_task_id=task_b.id))

    assert await repository.exists(task_a.id, task_b.id) is True
    assert await repository.exists(task_b.id, task_a.id) is False


async def test_delete_removes_the_edge(session, two_tasks) -> None:
    task_a, task_b = two_tasks
    repository = TaskDependencyRepository(session)
    dependency = await repository.add(
        TaskDependency(id=uuid4(), task_id=task_a.id, depends_on_task_id=task_b.id)
    )

    await repository.delete(dependency.id)

    assert await repository.get_by_id(dependency.id) is None
