from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.projects.repository.feature_repository import FeatureRepository
from aep.modules.projects.repository.project_repository import ProjectRepository
from aep.modules.projects.services import FeatureService as ProjectsFeatureService
from aep.modules.projects.services import ProjectService
from aep.modules.task_memory.domain.errors import (
    CyclicDependencyError,
    DuplicateDependencyError,
    FeatureNotFoundError,
    IllegalTaskStatusTransitionError,
    SelfDependencyError,
    TaskDependencyNotFoundError,
    TaskNotFoundError,
    UnmetDependenciesError,
)
from aep.modules.task_memory.domain.models import DependencyType, TaskStatus, TaskType
from aep.modules.task_memory.repository.execution_history_repository import (
    ExecutionHistoryRepository,
)
from aep.modules.task_memory.repository.task_dependency_repository import (
    TaskDependencyRepository,
)
from aep.modules.task_memory.repository.task_repository import TaskRepository
from aep.modules.task_memory.services.task_service import TaskService


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
async def feature(session):
    project = await ProjectService(ProjectRepository(session)).create_project(
        name="AEP", slug="aep", owner_user_id=uuid4()
    )
    projects_feature_service = ProjectsFeatureService(
        FeatureRepository(session), ProjectRepository(session)
    )
    return await projects_feature_service.create_feature(
        project_id=project.id, title="Dashboard", created_by=uuid4()
    )


@pytest.fixture
def task_service(session) -> TaskService:
    projects_feature_service = ProjectsFeatureService(
        FeatureRepository(session), ProjectRepository(session)
    )
    return TaskService(
        TaskRepository(session),
        TaskDependencyRepository(session),
        ExecutionHistoryRepository(session),
        projects_feature_service,
    )


async def test_create_task_succeeds(task_service: TaskService, feature) -> None:
    task = await task_service.create_task(feature_id=feature.id, title="Write endpoint", task_type=TaskType.CODE)

    assert task.title == "Write endpoint"
    assert task.status == TaskStatus.PENDING


async def test_create_task_raises_when_feature_missing(task_service: TaskService) -> None:
    with pytest.raises(FeatureNotFoundError):
        await task_service.create_task(feature_id=uuid4(), title="X", task_type=TaskType.CODE)


async def test_get_task_raises_not_found(task_service: TaskService) -> None:
    with pytest.raises(TaskNotFoundError):
        await task_service.get_task(uuid4())


async def test_transition_requires_an_actor(task_service: TaskService, feature) -> None:
    task = await task_service.create_task(feature_id=feature.id, title="X", task_type=TaskType.CODE)

    with pytest.raises(ValueError, match="changed_by"):
        await task_service.transition_status(task.id, to_status=TaskStatus.READY)


async def test_transition_rejects_illegal_edge(task_service: TaskService, feature) -> None:
    task = await task_service.create_task(feature_id=feature.id, title="X", task_type=TaskType.CODE)

    with pytest.raises(IllegalTaskStatusTransitionError):
        await task_service.transition_status(
            task.id, to_status=TaskStatus.MERGED, changed_by_user_id=uuid4()
        )


async def test_transition_to_running_blocked_by_unmet_dependency(task_service: TaskService, feature) -> None:
    blocker = await task_service.create_task(feature_id=feature.id, title="Blocker", task_type=TaskType.CODE)
    dependent = await task_service.create_task(feature_id=feature.id, title="Dependent", task_type=TaskType.CODE)
    await task_service.add_dependency(dependent.id, depends_on_task_id=blocker.id)
    user_id = uuid4()
    await task_service.transition_status(dependent.id, to_status=TaskStatus.READY, changed_by_user_id=user_id)

    with pytest.raises(UnmetDependenciesError):
        await task_service.transition_status(
            dependent.id, to_status=TaskStatus.RUNNING, changed_by_user_id=user_id
        )


async def test_transition_to_running_succeeds_once_dependency_is_merged(
    task_service: TaskService, feature
) -> None:
    blocker = await task_service.create_task(feature_id=feature.id, title="Blocker", task_type=TaskType.CODE)
    dependent = await task_service.create_task(feature_id=feature.id, title="Dependent", task_type=TaskType.CODE)
    await task_service.add_dependency(dependent.id, depends_on_task_id=blocker.id)
    user_id = uuid4()

    # Walk the blocker all the way to merged.
    for status in (
        TaskStatus.READY,
        TaskStatus.RUNNING,
        TaskStatus.EVALUATING,
        TaskStatus.AWAITING_APPROVAL,
        TaskStatus.APPROVED,
        TaskStatus.MERGED,
    ):
        await task_service.transition_status(blocker.id, to_status=status, changed_by_user_id=user_id)

    await task_service.transition_status(dependent.id, to_status=TaskStatus.READY, changed_by_user_id=user_id)
    updated = await task_service.transition_status(
        dependent.id, to_status=TaskStatus.RUNNING, changed_by_user_id=user_id
    )

    assert updated.status == TaskStatus.RUNNING


async def test_transition_records_execution_history(task_service: TaskService, feature) -> None:
    task = await task_service.create_task(feature_id=feature.id, title="X", task_type=TaskType.CODE)
    user_id = uuid4()

    await task_service.transition_status(task.id, to_status=TaskStatus.READY, changed_by_user_id=user_id)

    history, _, _ = await task_service.list_execution_history(task.id)
    assert len(history) == 1
    assert history[0].from_status == TaskStatus.PENDING
    assert history[0].to_status == TaskStatus.READY
    assert history[0].changed_by_user_id == user_id


async def test_add_dependency_rejects_self_dependency(task_service: TaskService, feature) -> None:
    task = await task_service.create_task(feature_id=feature.id, title="X", task_type=TaskType.CODE)

    with pytest.raises(SelfDependencyError):
        await task_service.add_dependency(task.id, depends_on_task_id=task.id)


async def test_add_dependency_rejects_duplicate_edge(task_service: TaskService, feature) -> None:
    a = await task_service.create_task(feature_id=feature.id, title="A", task_type=TaskType.CODE)
    b = await task_service.create_task(feature_id=feature.id, title="B", task_type=TaskType.CODE)
    await task_service.add_dependency(a.id, depends_on_task_id=b.id)

    with pytest.raises(DuplicateDependencyError):
        await task_service.add_dependency(a.id, depends_on_task_id=b.id)


async def test_add_dependency_rejects_direct_cycle(task_service: TaskService, feature) -> None:
    a = await task_service.create_task(feature_id=feature.id, title="A", task_type=TaskType.CODE)
    b = await task_service.create_task(feature_id=feature.id, title="B", task_type=TaskType.CODE)
    await task_service.add_dependency(a.id, depends_on_task_id=b.id)

    with pytest.raises(CyclicDependencyError):
        await task_service.add_dependency(b.id, depends_on_task_id=a.id)


async def test_add_dependency_rejects_transitive_cycle(task_service: TaskService, feature) -> None:
    a = await task_service.create_task(feature_id=feature.id, title="A", task_type=TaskType.CODE)
    b = await task_service.create_task(feature_id=feature.id, title="B", task_type=TaskType.CODE)
    c = await task_service.create_task(feature_id=feature.id, title="C", task_type=TaskType.CODE)
    await task_service.add_dependency(a.id, depends_on_task_id=b.id)  # a depends on b
    await task_service.add_dependency(b.id, depends_on_task_id=c.id)  # b depends on c

    with pytest.raises(CyclicDependencyError):
        # c depends on a would close the cycle a -> b -> c -> a
        await task_service.add_dependency(c.id, depends_on_task_id=a.id)


async def test_remove_dependency_raises_when_missing(task_service: TaskService) -> None:
    with pytest.raises(TaskDependencyNotFoundError):
        await task_service.remove_dependency(uuid4())


async def test_add_dependency_supports_informs_type(task_service: TaskService, feature) -> None:
    a = await task_service.create_task(feature_id=feature.id, title="A", task_type=TaskType.CODE)
    b = await task_service.create_task(feature_id=feature.id, title="B", task_type=TaskType.CODE)

    dependency = await task_service.add_dependency(
        a.id, depends_on_task_id=b.id, dependency_type=DependencyType.INFORMS
    )

    assert dependency.dependency_type == DependencyType.INFORMS
