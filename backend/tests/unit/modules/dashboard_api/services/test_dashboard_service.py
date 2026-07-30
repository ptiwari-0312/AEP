"""End-to-end tests for the Dashboard API's composition service against real collaborators: real
`projects`/`task_memory`/`context_builder`/`orchestrator`/`evaluation`/`auth` services, a real
`EchoAgent` run, and real evaluators — no mocks, matching this codebase's standing rule of
testing against real dependencies wherever one is free to construct.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from aep_agent_sdk import AgentType

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.auth.repository.audit_event_repository import AuditEventRepository
from aep.modules.auth.repository.models import (
    AuditEventModel,  # noqa: F401 - registers table
)
from aep.modules.auth.services import AuditService
from aep.modules.context_builder.repository.context_package_repository import (
    ContextPackageRepository,
)
from aep.modules.context_builder.repository.context_package_source_repository import (
    ContextPackageSourceRepository,
)
from aep.modules.context_builder.repository.source_document_repository import (
    SourceDocumentRepository,
)
from aep.modules.context_builder.services.context_builder_service import (
    ContextBuilderService,
)
from aep.modules.context_builder.services.indexing import SourceDocumentIndexer
from aep.modules.dashboard_api.domain.errors import ProjectNotFoundError
from aep.modules.dashboard_api.services.dashboard_service import DashboardService
from aep.modules.evaluation.domain.models import EvaluatorType
from aep.modules.evaluation.repository.evaluation_repository import EvaluationRepository
from aep.modules.evaluation.repository.evaluation_result_repository import (
    EvaluationResultRepository,
)
from aep.modules.evaluation.services.evaluation_service import EvaluationService
from aep.modules.evaluation.services.evaluator_registry import EvaluatorRegistry
from aep.modules.orchestrator.repository.agent_repository import AgentRepository
from aep.modules.orchestrator.repository.agent_run_repository import AgentRunRepository
from aep.modules.orchestrator.services.agent_registry import AgentRegistry
from aep.modules.orchestrator.services.agent_run_service import AgentRunService
from aep.modules.orchestrator.services.agent_service import AgentService
from aep.modules.orchestrator.services.run_events import RunEventBroker
from aep.modules.orchestrator.services.run_registry import RunRegistry
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
async def _sqlite_backed_db(tmp_path_factory, monkeypatch):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
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
def context_builder_service(session, task_service, feature_service, project_service) -> ContextBuilderService:
    return ContextBuilderService(
        SourceDocumentRepository(session),
        ContextPackageRepository(session),
        ContextPackageSourceRepository(session),
        task_service,
        feature_service,
        project_service,
    )


@pytest.fixture
def agent_service(session) -> AgentService:
    return AgentService(AgentRepository(session))


@pytest.fixture
def run_registry() -> RunRegistry:
    return RunRegistry()


@pytest.fixture
def run_event_broker() -> RunEventBroker:
    return RunEventBroker()


@pytest.fixture
def agent_run_service(
    session, task_service, context_builder_service, run_registry, run_event_broker
) -> AgentRunService:
    return AgentRunService(
        AgentRepository(session),
        AgentRunRepository(session),
        task_service,
        context_builder_service,
        AgentRegistry(),
        run_registry,
        run_event_broker,
    )


@pytest.fixture
def evaluation_service(session, agent_run_service) -> EvaluationService:
    return EvaluationService(
        EvaluationRepository(session), EvaluationResultRepository(session), agent_run_service, EvaluatorRegistry()
    )


@pytest.fixture
def audit_service(session) -> AuditService:
    return AuditService(AuditEventRepository(session))


@pytest.fixture
def dashboard_service(
    project_service, feature_service, task_service, agent_run_service, agent_service, evaluation_service, audit_service
) -> DashboardService:
    return DashboardService(
        project_service, feature_service, task_service, agent_run_service, agent_service, evaluation_service, audit_service
    )


@pytest.fixture
async def project(project_service):
    return await project_service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())


@pytest.fixture
async def feature(feature_service, project):
    return await feature_service.create_feature(
        project_id=project.id, title="Add login", created_by=uuid4()
    )


@pytest.fixture
async def ready_task(task_service, feature):
    task = await task_service.create_task(
        feature_id=feature.id, title="Implement login", task_type=TaskType.CODE
    )
    return await task_service.transition_status(
        task.id, to_status=TaskStatus.READY, changed_by_user_id=uuid4()
    )


@pytest.fixture
async def succeeded_run(
    session, agent_run_service, agent_service, context_builder_service, project, ready_task, run_registry, tmp_path
):
    (tmp_path / "auth.py").write_text("def login(user):\n    return authenticate(user)\n")
    indexer = SourceDocumentIndexer(SourceDocumentRepository(session))
    await indexer.index_directory(project.id, tmp_path)
    package = await context_builder_service.generate_context_package(ready_task.id, max_tokens=100_000)

    agent = await agent_service.register_agent(name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")
    await agent_run_service.assign_agent(ready_task.id, agent_id=agent.id)
    run = await agent_run_service.start_run(
        ready_task.id, provider="claude", model_name="claude-x", context_package_id=package.id
    )
    await session.commit()
    await run_registry.wait_for(run.id)
    return await agent_run_service.get_run(run.id)


async def test_get_overview_counts_active_projects(
    dashboard_service: DashboardService, project
) -> None:
    overview = await dashboard_service.get_overview()

    assert overview.active_projects == 1


async def test_get_overview_counts_running_agents(
    dashboard_service: DashboardService,
    agent_run_service,
    agent_service,
    context_builder_service,
    project,
    ready_task,
    session,
    tmp_path,
) -> None:
    (tmp_path / "auth.py").write_text("def login(user):\n    return authenticate(user)\n")
    indexer = SourceDocumentIndexer(SourceDocumentRepository(session))
    await indexer.index_directory(project.id, tmp_path)
    package = await context_builder_service.generate_context_package(ready_task.id, max_tokens=100_000)
    slow_agent = await agent_service.register_agent(
        name="SlowAgent",
        agent_type=AgentType.CODING,
        version="1.0.0",
        config={"execution_delay_seconds": 5.0, "poll_interval_seconds": 0.5},
    )
    await agent_run_service.assign_agent(ready_task.id, agent_id=slow_agent.id)
    await agent_run_service.start_run(
        ready_task.id, provider="claude", model_name="claude-x", context_package_id=package.id
    )
    await session.commit()

    overview = await dashboard_service.get_overview()

    assert overview.running_agents == 1


async def test_get_overview_counts_pending_approvals(
    dashboard_service: DashboardService, task_service, succeeded_run, ready_task
) -> None:
    task = await task_service.get_task(ready_task.id)
    assert task.status == TaskStatus.AWAITING_APPROVAL  # EchoAgent succeeds -> self-eval passes

    overview = await dashboard_service.get_overview()

    assert overview.pending_approvals == 1


async def test_get_overview_includes_recent_evaluations_and_audit_events(
    dashboard_service: DashboardService, evaluation_service, audit_service, succeeded_run
) -> None:
    await evaluation_service.trigger_evaluations(
        succeeded_run.id, evaluator_types=[EvaluatorType.PERFORMANCE]
    )
    await audit_service.record_event(
        event_type="task.approved", entity_type="task", entity_id=uuid4(), actor_user_id=uuid4()
    )

    overview = await dashboard_service.get_overview()

    assert len(overview.recent_evaluations) == 1
    assert len(overview.recent_audit_events) == 1


async def test_get_task_graph_includes_tasks_and_dependencies(
    dashboard_service: DashboardService, task_service, project, feature
) -> None:
    blocker = await task_service.create_task(
        feature_id=feature.id, title="Design schema", task_type=TaskType.ARCHITECT
    )
    dependent = await task_service.create_task(
        feature_id=feature.id, title="Implement endpoint", task_type=TaskType.CODE
    )
    await task_service.add_dependency(dependent.id, depends_on_task_id=blocker.id)

    graph = await dashboard_service.get_task_graph(project.id)

    assert {node.task_id for node in graph.nodes} == {blocker.id, dependent.id}
    assert len(graph.edges) == 1
    assert graph.edges[0].task_id == dependent.id
    assert graph.edges[0].depends_on_task_id == blocker.id


async def test_get_task_graph_raises_when_project_missing(
    dashboard_service: DashboardService,
) -> None:
    with pytest.raises(ProjectNotFoundError):
        await dashboard_service.get_task_graph(uuid4())


async def test_get_task_graph_covers_multiple_features(
    dashboard_service: DashboardService, feature_service, task_service, project
) -> None:
    feature_a = await feature_service.create_feature(
        project_id=project.id, title="Feature A", created_by=uuid4()
    )
    feature_b = await feature_service.create_feature(
        project_id=project.id, title="Feature B", created_by=uuid4()
    )
    task_a = await task_service.create_task(feature_id=feature_a.id, title="A", task_type=TaskType.CODE)
    task_b = await task_service.create_task(feature_id=feature_b.id, title="B", task_type=TaskType.CODE)

    graph = await dashboard_service.get_task_graph(project.id)

    assert {node.task_id for node in graph.nodes} == {task_a.id, task_b.id}


async def test_list_running_agents_enriches_with_task_project_and_agent_context(
    dashboard_service: DashboardService,
    agent_run_service,
    agent_service,
    context_builder_service,
    project,
    ready_task,
    session,
    tmp_path,
) -> None:
    (tmp_path / "auth.py").write_text("def login(user):\n    return authenticate(user)\n")
    indexer = SourceDocumentIndexer(SourceDocumentRepository(session))
    await indexer.index_directory(project.id, tmp_path)
    package = await context_builder_service.generate_context_package(ready_task.id, max_tokens=100_000)
    slow_agent = await agent_service.register_agent(
        name="SlowAgent",
        agent_type=AgentType.CODING,
        version="1.0.0",
        config={"execution_delay_seconds": 5.0, "poll_interval_seconds": 0.5},
    )
    await agent_run_service.assign_agent(ready_task.id, agent_id=slow_agent.id)
    run = await agent_run_service.start_run(
        ready_task.id, provider="claude", model_name="claude-x", context_package_id=package.id
    )
    await session.commit()

    running = await dashboard_service.list_running_agents()

    assert len(running) == 1
    summary = running[0]
    assert summary.agent_run_id == run.id
    assert summary.task_title == "Implement login"
    assert summary.project_name == "AEP"
    assert summary.agent_name == "SlowAgent"
    assert summary.agent_type == "coding"


async def test_list_running_agents_empty_when_nothing_running(
    dashboard_service: DashboardService,
) -> None:
    assert await dashboard_service.list_running_agents() == []
