"""End-to-end tests for the Agent Orchestrator's run pipeline against real collaborators: real
SQLite-backed `task_memory.TaskService`/`projects.FeatureService`/`projects.ProjectService`,
`context_builder.ContextBuilderService` (with real local files indexed via
`SourceDocumentIndexer`), and the real `EchoAgent` (a genuine `BaseAgent` subclass, not a mock)
run via real `asyncio` background tasks — no mocks, matching this codebase's standing rule of
testing against real dependencies wherever one is free to construct.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

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
from aep.modules.orchestrator.domain.errors import (
    AgentDisabledError,
    AgentNotFoundError,
    AgentRunNotCancellableError,
    AgentRunNotRetryableError,
    ContextPackageNotFoundError,
    TaskHasNoAssignedAgentError,
    TaskNotFoundError,
)
from aep.modules.orchestrator.domain.models import AgentRunStatus, AgentType
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
    # A fresh instance per test, not the process-wide `get_run_registry()` singleton — this test
    # controls its own lifecycle and shouldn't leak state across tests.
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
async def context_package(session, context_builder_service, project, ready_task, tmp_path):
    (tmp_path / "auth.py").write_text("def login(user):\n    return authenticate(user)\n")
    indexer = SourceDocumentIndexer(SourceDocumentRepository(session))
    await indexer.index_directory(project.id, tmp_path)
    return await context_builder_service.generate_context_package(
        ready_task.id, max_tokens=100_000
    )


@pytest.fixture
async def enabled_agent(agent_service):
    return await agent_service.register_agent(
        name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0"
    )


@pytest.fixture
async def disabled_agent(agent_service):
    agent = await agent_service.register_agent(
        name="DisabledAgent", agent_type=AgentType.CODING, version="1.0.0"
    )
    return await agent_service.update_agent(agent.id, is_enabled=False)


@pytest.fixture
async def failing_agent(agent_service):
    return await agent_service.register_agent(
        name="FailingAgent", agent_type=AgentType.CODING, version="1.0.0", config={"fail": True}
    )


async def test_assign_agent_sets_assigned_agent_id(
    agent_run_service, ready_task, enabled_agent
) -> None:
    summary = await agent_run_service.assign_agent(ready_task.id, agent_id=enabled_agent.id)

    assert summary.assigned_agent_id == enabled_agent.id


async def test_assign_agent_raises_when_task_missing(agent_run_service, enabled_agent) -> None:
    with pytest.raises(TaskNotFoundError):
        await agent_run_service.assign_agent(uuid4(), agent_id=enabled_agent.id)


async def test_assign_agent_raises_when_agent_missing(agent_run_service, ready_task) -> None:
    with pytest.raises(AgentNotFoundError):
        await agent_run_service.assign_agent(ready_task.id, agent_id=uuid4())


async def test_assign_disabled_agent_is_rejected(
    agent_run_service, ready_task, disabled_agent
) -> None:
    with pytest.raises(AgentDisabledError):
        await agent_run_service.assign_agent(ready_task.id, agent_id=disabled_agent.id)


async def test_start_run_without_assignment_is_rejected(
    agent_run_service, ready_task, context_package
) -> None:
    with pytest.raises(TaskHasNoAssignedAgentError):
        await agent_run_service.start_run(
            ready_task.id,
            provider="claude",
            model_name="claude-x",
            context_package_id=context_package.id,
        )


async def test_start_run_with_mismatched_context_package_is_rejected(
    agent_run_service, ready_task, enabled_agent
) -> None:
    await agent_run_service.assign_agent(ready_task.id, agent_id=enabled_agent.id)

    with pytest.raises(ContextPackageNotFoundError):
        await agent_run_service.start_run(
            ready_task.id, provider="claude", model_name="claude-x", context_package_id=uuid4()
        )


async def test_successful_run_transitions_task_to_awaiting_approval(
    agent_run_service, task_service, run_registry, session, ready_task, enabled_agent, context_package
) -> None:
    await agent_run_service.assign_agent(ready_task.id, agent_id=enabled_agent.id)

    run = await agent_run_service.start_run(
        ready_task.id,
        provider="claude",
        model_name="claude-x",
        context_package_id=context_package.id,
    )
    # Commits the outer session's still-open transaction — the background task opens its *own*
    # DB connection to persist the run's outcome (see agent_run_service.py's docstring), and
    # SQLite (unlike Postgres) blocks a second writer behind any still-open transaction on the
    # same file. A real HTTP request commits at the request boundary before this point; this
    # test has to do it explicitly since it calls the service directly.
    await session.commit()
    await run_registry.wait_for(run.id)

    settled = await agent_run_service.get_run(run.id)
    assert settled.status == AgentRunStatus.SUCCEEDED
    assert settled.input_tokens is not None and settled.input_tokens > 0

    task = await task_service.get_task(ready_task.id)
    assert task.status == TaskStatus.AWAITING_APPROVAL


async def test_failing_run_transitions_task_to_failed(
    agent_run_service, task_service, run_registry, session, ready_task, failing_agent, context_package
) -> None:
    await agent_run_service.assign_agent(ready_task.id, agent_id=failing_agent.id)

    run = await agent_run_service.start_run(
        ready_task.id,
        provider="claude",
        model_name="claude-x",
        context_package_id=context_package.id,
    )
    await session.commit()  # see test_successful_run_transitions_task_to_awaiting_approval
    await run_registry.wait_for(run.id)

    settled = await agent_run_service.get_run(run.id)
    assert settled.status == AgentRunStatus.FAILED
    assert settled.error_message is not None

    task = await task_service.get_task(ready_task.id)
    assert task.status == TaskStatus.FAILED


async def test_cancel_run_transitions_task_to_cancelled(
    agent_run_service, agent_service, task_service, run_registry, session, ready_task, context_package
) -> None:
    slow_agent = await agent_service.register_agent(
        name="SlowAgent",
        agent_type=AgentType.CODING,
        version="1.0.0",
        config={"execution_delay_seconds": 2.0, "poll_interval_seconds": 0.02},
    )
    await agent_run_service.assign_agent(ready_task.id, agent_id=slow_agent.id)

    run = await agent_run_service.start_run(
        ready_task.id,
        provider="claude",
        model_name="claude-x",
        context_package_id=context_package.id,
    )
    await session.commit()  # see test_successful_run_transitions_task_to_awaiting_approval
    cancelled = await agent_run_service.cancel_run(run.id)
    assert cancelled.id == run.id

    await run_registry.wait_for(run.id)

    settled = await agent_run_service.get_run(run.id)
    assert settled.status == AgentRunStatus.CANCELLED

    task = await task_service.get_task(ready_task.id)
    assert task.status == TaskStatus.CANCELLED


async def test_cancel_already_settled_run_is_rejected(
    agent_run_service, run_registry, session, ready_task, enabled_agent, context_package
) -> None:
    await agent_run_service.assign_agent(ready_task.id, agent_id=enabled_agent.id)
    run = await agent_run_service.start_run(
        ready_task.id,
        provider="claude",
        model_name="claude-x",
        context_package_id=context_package.id,
    )
    await session.commit()  # see test_successful_run_transitions_task_to_awaiting_approval
    await run_registry.wait_for(run.id)

    with pytest.raises(AgentRunNotCancellableError):
        await agent_run_service.cancel_run(run.id)


async def test_retry_run_requires_failed_status(
    agent_run_service, run_registry, session, ready_task, enabled_agent, context_package
) -> None:
    await agent_run_service.assign_agent(ready_task.id, agent_id=enabled_agent.id)
    run = await agent_run_service.start_run(
        ready_task.id,
        provider="claude",
        model_name="claude-x",
        context_package_id=context_package.id,
    )
    await session.commit()  # see test_successful_run_transitions_task_to_awaiting_approval
    await run_registry.wait_for(run.id)

    with pytest.raises(AgentRunNotRetryableError):
        await agent_run_service.retry_run(run.id)


async def test_retry_run_increments_attempt_number(
    agent_run_service, task_service, run_registry, session, ready_task, failing_agent, context_package
) -> None:
    await agent_run_service.assign_agent(ready_task.id, agent_id=failing_agent.id)
    run = await agent_run_service.start_run(
        ready_task.id,
        provider="claude",
        model_name="claude-x",
        context_package_id=context_package.id,
    )
    await session.commit()  # see test_successful_run_transitions_task_to_awaiting_approval
    await run_registry.wait_for(run.id)
    assert (await agent_run_service.get_run(run.id)).status == AgentRunStatus.FAILED

    retried = await agent_run_service.retry_run(run.id)
    assert retried.attempt_number == 2
    await session.commit()  # same reason — retry_run() launches a second background writer
    await run_registry.wait_for(run.id)

    settled = await agent_run_service.get_run(run.id)
    assert settled.attempt_number == 2
    assert settled.status == AgentRunStatus.FAILED  # still configured to fail


async def test_subscribe_to_run_events_of_a_settled_run_yields_one_terminal_event(
    agent_run_service, run_registry, session, ready_task, enabled_agent, context_package
) -> None:
    await agent_run_service.assign_agent(ready_task.id, agent_id=enabled_agent.id)
    run = await agent_run_service.start_run(
        ready_task.id,
        provider="claude",
        model_name="claude-x",
        context_package_id=context_package.id,
    )
    await session.commit()  # see test_successful_run_transitions_task_to_awaiting_approval
    await run_registry.wait_for(run.id)

    events = [
        event async for event in agent_run_service.subscribe_to_run_events(run.id)
    ]

    assert len(events) == 1
    event_type, payload = events[0]
    assert event_type == "agent_run.persisted"
    assert payload["status"] == "succeeded"