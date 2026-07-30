from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.auth.repository.audit_event_repository import AuditEventRepository
from aep.modules.auth.repository.models import (
    AuditEventModel,  # noqa: F401 - registers table
)
from aep.modules.auth.services import AuditService
from aep.modules.orchestrator.domain.errors import (
    TaskNotFoundError,
    TaskTransitionNotAllowedError,
)
from aep.modules.orchestrator.services.task_review_service import TaskReviewService
from aep.modules.projects.repository.feature_repository import FeatureRepository
from aep.modules.projects.repository.project_repository import ProjectRepository
from aep.modules.projects.services import FeatureService, ProjectService
from aep.modules.task_memory.domain.models import TaskStatus, TaskType
from aep.modules.task_memory.repository.execution_history_repository import (
    ExecutionHistoryRepository,
)
from aep.modules.task_memory.repository.task_dependency_repository import (
    TaskDependencyRepository,
)
from aep.modules.task_memory.repository.task_repository import TaskRepository
from aep.modules.task_memory.services import TaskService


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
def project_service(session) -> ProjectService:
    return ProjectService(ProjectRepository(session))


@pytest.fixture
def feature_service(session) -> FeatureService:
    return FeatureService(FeatureRepository(session), ProjectRepository(session))


@pytest.fixture
def task_service(session, feature_service) -> TaskService:
    return TaskService(
        TaskRepository(session),
        TaskDependencyRepository(session),
        ExecutionHistoryRepository(session),
        feature_service,
    )


@pytest.fixture
def audit_service(session) -> AuditService:
    return AuditService(AuditEventRepository(session))


@pytest.fixture
def review_service(task_service, audit_service) -> TaskReviewService:
    return TaskReviewService(task_service, audit_service)


@pytest.fixture
async def project(project_service):
    return await project_service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())


@pytest.fixture
async def feature(feature_service, project):
    return await feature_service.create_feature(
        project_id=project.id, title="Add login", created_by=uuid4()
    )


@pytest.fixture
async def awaiting_approval_task(task_service, feature):
    task = await task_service.create_task(
        feature_id=feature.id, title="Implement login", task_type=TaskType.CODE
    )
    for status in (TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.EVALUATING):
        task = await task_service.transition_status(
            task.id, to_status=status, changed_by_user_id=uuid4()
        )
    return await task_service.transition_status(
        task.id, to_status=TaskStatus.AWAITING_APPROVAL, changed_by_user_id=uuid4()
    )


async def test_approve_transitions_task_and_writes_audit_event(
    review_service, audit_service, awaiting_approval_task
) -> None:
    reviewer_id = uuid4()

    summary = await review_service.approve(
        awaiting_approval_task.id, reviewer_user_id=reviewer_id, comment="looks good"
    )

    assert summary.status == "approved"
    events, _cursor, _has_more = await audit_service.list_events(
        entity_type="task", entity_id=awaiting_approval_task.id
    )
    assert len(events) == 1
    assert events[0].event_type == "task.approved"
    assert events[0].actor_user_id == reviewer_id
    assert events[0].payload == {"comment": "looks good"}


async def test_reject_transitions_task_without_audit_event(
    review_service, audit_service, awaiting_approval_task
) -> None:
    summary = await review_service.reject(
        awaiting_approval_task.id, reviewer_user_id=uuid4(), comment="needs rework"
    )

    assert summary.status == "rejected"
    events, _cursor, _has_more = await audit_service.list_events(
        entity_type="task", entity_id=awaiting_approval_task.id
    )
    assert len(events) == 0


async def test_merge_requires_approved_status(review_service, awaiting_approval_task) -> None:
    with pytest.raises(TaskTransitionNotAllowedError):
        await review_service.merge(awaiting_approval_task.id, actor_user_id=uuid4())


async def test_approve_then_merge(review_service, awaiting_approval_task) -> None:
    await review_service.approve(awaiting_approval_task.id, reviewer_user_id=uuid4())

    merged = await review_service.merge(awaiting_approval_task.id, actor_user_id=uuid4())

    assert merged.status == "merged"


async def test_approve_raises_when_task_missing(review_service) -> None:
    with pytest.raises(TaskNotFoundError):
        await review_service.approve(uuid4(), reviewer_user_id=uuid4())
