"""End-to-end tests for the Evaluation Framework against real collaborators: a real, fully
succeeded `orchestrator.AgentRunService` run (itself backed by real
`task_memory`/`projects`/`context_builder` services and a real `EchoAgent` execution) — no
mocks, matching this codebase's standing rule of testing against real dependencies wherever one
is free to construct.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from aep_agent_sdk import AgentType

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
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
from aep.modules.evaluation.domain.errors import (
    AgentRunNotFoundError,
    AgentRunNotSucceededError,
    EvaluationNotFoundError,
    EvaluatorTypeNotRegisteredError,
    TaskNotFoundError,
)
from aep.modules.evaluation.domain.models import EvaluatorType
from aep.modules.evaluation.repository.evaluation_repository import EvaluationRepository
from aep.modules.evaluation.repository.evaluation_result_repository import (
    EvaluationResultRepository,
)
from aep.modules.evaluation.services.evaluation_service import EvaluationService
from aep.modules.evaluation.services.evaluator_registry import EvaluatorRegistry
from aep.modules.evaluation.services.reference_evaluators import EchoJudgeEvaluator
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
        EvaluationRepository(session),
        EvaluationResultRepository(session),
        agent_run_service,
        EvaluatorRegistry(),
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


async def _make_context_package(context_builder_service, project, task, tmp_path, session):
    (tmp_path / "auth.py").write_text("def login(user):\n    return authenticate(user)\n")
    indexer = SourceDocumentIndexer(SourceDocumentRepository(session))
    await indexer.index_directory(project.id, tmp_path)
    return await context_builder_service.generate_context_package(task.id, max_tokens=100_000)


@pytest.fixture
async def succeeded_run(
    session,
    agent_run_service,
    agent_service,
    context_builder_service,
    project,
    ready_task,
    run_registry,
    tmp_path,
):
    package = await _make_context_package(context_builder_service, project, ready_task, tmp_path, session)
    agent = await agent_service.register_agent(
        name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0"
    )
    await agent_run_service.assign_agent(ready_task.id, agent_id=agent.id)
    run = await agent_run_service.start_run(
        ready_task.id, provider="claude", model_name="claude-x", context_package_id=package.id
    )
    await session.commit()
    await run_registry.wait_for(run.id)
    return await agent_run_service.get_run(run.id)


async def test_trigger_evaluations_persists_one_row_per_evaluator_type(
    evaluation_service: EvaluationService, succeeded_run
) -> None:
    evaluations = await evaluation_service.trigger_evaluations(
        succeeded_run.id, evaluator_types=[EvaluatorType.PERFORMANCE, EvaluatorType.LLM_JUDGE]
    )

    assert {e.evaluator_type for e in evaluations} == {
        EvaluatorType.PERFORMANCE,
        EvaluatorType.LLM_JUDGE,
    }
    for evaluation in evaluations:
        results = await evaluation_service.list_results_for_evaluation(evaluation.id)
        assert len(results) >= 1


async def test_trigger_evaluations_raises_when_run_missing(
    evaluation_service: EvaluationService,
) -> None:
    with pytest.raises(AgentRunNotFoundError):
        await evaluation_service.trigger_evaluations(
            uuid4(), evaluator_types=[EvaluatorType.PERFORMANCE]
        )


async def test_trigger_evaluations_rejects_unregistered_evaluator_type(
    evaluation_service: EvaluationService, succeeded_run
) -> None:
    with pytest.raises(EvaluatorTypeNotRegisteredError):
        await evaluation_service.trigger_evaluations(
            succeeded_run.id, evaluator_types=[EvaluatorType.UNIT_TEST]
        )


async def test_trigger_evaluations_rejects_run_not_yet_succeeded(
    evaluation_service: EvaluationService,
    agent_run_service,
    agent_service,
    context_builder_service,
    task_service,
    project,
    feature,
    session,
    tmp_path,
) -> None:
    other_task = await task_service.create_task(
        feature_id=feature.id, title="Slow task", task_type=TaskType.CODE
    )
    other_task = await task_service.transition_status(
        other_task.id, to_status=TaskStatus.READY, changed_by_user_id=uuid4()
    )
    slow_dir = tmp_path / "slow"
    slow_dir.mkdir()
    package = await _make_context_package(context_builder_service, project, other_task, slow_dir, session)
    slow_agent = await agent_service.register_agent(
        name="SlowAgent",
        agent_type=AgentType.CODING,
        version="1.0.0",
        config={"execution_delay_seconds": 2.0, "poll_interval_seconds": 0.02},
    )
    await agent_run_service.assign_agent(other_task.id, agent_id=slow_agent.id)
    run = await agent_run_service.start_run(
        other_task.id, provider="claude", model_name="claude-x", context_package_id=package.id
    )
    await session.commit()

    with pytest.raises(AgentRunNotSucceededError):
        await evaluation_service.trigger_evaluations(
            run.id, evaluator_types=[EvaluatorType.PERFORMANCE]
        )


async def test_get_quality_gate_is_pending_before_any_evaluation(
    evaluation_service: EvaluationService, succeeded_run, ready_task
) -> None:
    gate = await evaluation_service.get_quality_gate(ready_task.id)

    assert gate.overall == "pending"
    assert gate.agent_run_id == succeeded_run.id
    assert gate.evaluations == []


async def test_get_quality_gate_passes_when_all_evaluations_pass(
    evaluation_service: EvaluationService, succeeded_run, ready_task
) -> None:
    await evaluation_service.trigger_evaluations(
        succeeded_run.id, evaluator_types=[EvaluatorType.LLM_JUDGE]
    )

    gate = await evaluation_service.get_quality_gate(ready_task.id)

    assert gate.overall == "passed"
    assert len(gate.evaluations) == 1


async def test_get_quality_gate_fails_when_an_evaluation_fails(
    evaluation_service: EvaluationService, agent_run_service, succeeded_run, ready_task, session
) -> None:
    failing_registry = EvaluatorRegistry(
        factories={
            EvaluatorType.LLM_JUDGE: lambda **kwargs: EchoJudgeEvaluator(config={"passed": False}),
        }
    )
    failing_service = EvaluationService(
        EvaluationRepository(session),
        EvaluationResultRepository(session),
        agent_run_service,
        failing_registry,
    )

    await failing_service.trigger_evaluations(
        succeeded_run.id, evaluator_types=[EvaluatorType.LLM_JUDGE]
    )

    gate = await failing_service.get_quality_gate(ready_task.id)

    assert gate.overall == "failed"


async def test_get_quality_gate_returns_pending_agent_run_id_none_without_any_run(
    evaluation_service: EvaluationService, task_service, feature_service, project_service
) -> None:
    project = await project_service.create_project(name="Other", slug="other", owner_user_id=uuid4())
    feature = await feature_service.create_feature(
        project_id=project.id, title="F", created_by=uuid4()
    )
    task = await task_service.create_task(feature_id=feature.id, title="T", task_type=TaskType.CODE)

    gate = await evaluation_service.get_quality_gate(task.id)

    assert gate.overall == "pending"
    assert gate.agent_run_id is None


async def test_get_quality_gate_raises_when_task_missing(
    evaluation_service: EvaluationService,
) -> None:
    with pytest.raises(TaskNotFoundError):
        await evaluation_service.get_quality_gate(uuid4())


async def test_get_evaluation_raises_when_missing(evaluation_service: EvaluationService) -> None:
    with pytest.raises(EvaluationNotFoundError):
        await evaluation_service.get_evaluation(uuid4())
