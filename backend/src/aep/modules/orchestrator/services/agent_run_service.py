"""Use-case orchestration for assigning agents to tasks and driving `agent_runs`
(docs/architecture/04-api-design.md §5).

Cross-module composition: starting a run needs `task_memory`'s `TaskService` (to confirm the
task, read/set `assigned_agent_id`, and drive its status transitions) and `context_builder`'s
`ContextBuilderService` (to confirm the context package and assemble its actual text via
`assemble_content()`) — both obtained as constructor collaborators, never by importing either
module's `repository/` directly.

Execution itself runs as an in-process `asyncio` background task (see `run_registry.py`'s
docstring for why), which means the request that started it returns before the run settles — the
background task needs its *own* DB session, since the request-scoped one is gone by the time it
runs. Rather than import `task_memory`/`projects`' `repository/` to rebuild their services
against that new session (which the "call the other module's `services/`, never its
`repository/`" rule exists to prevent), it calls those modules' own `api/dependencies.py`
provider functions directly with an explicit session — the same functions FastAPI's `Depends()`
would call, just invoked as plain Python functions outside of a request, since no HTTP request
exists for a background task to hang a `Depends()` chain off of.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from aep_agent_sdk import AgentReport, BaseAgent, TaskContext
from aep_agent_sdk import AgentRunStatus as SdkAgentRunStatus

from aep.core.db import get_session_factory, utcnow
from aep.modules.context_builder.domain.errors import (
    ContextPackageNotFoundError as ContextBuilderContextPackageNotFoundError,
)
from aep.modules.context_builder.services import ContextBuilderService
from aep.modules.projects.api.dependencies import (
    get_feature_service as get_projects_feature_service,
)
from aep.modules.task_memory.api.dependencies import (
    get_task_service as get_task_memory_task_service,
)
from aep.modules.task_memory.domain.errors import (
    IllegalTaskStatusTransitionError as TaskMemoryIllegalTransitionError,
)
from aep.modules.task_memory.domain.errors import (
    TaskNotFoundError as TaskMemoryTaskNotFoundError,
)
from aep.modules.task_memory.domain.errors import (
    UnmetDependenciesError as TaskMemoryUnmetDependenciesError,
)
from aep.modules.task_memory.domain.models import Task as TaskMemoryTask
from aep.modules.task_memory.domain.models import TaskStatus as TaskMemoryTaskStatus
from aep.modules.task_memory.services import TaskService as TaskMemoryTaskService

from ..domain.errors import (
    AgentDisabledError,
    AgentNotFoundError,
    AgentRunNotCancellableError,
    AgentRunNotFoundError,
    AgentRunNotRetryableError,
    ContextPackageNotFoundError,
    TaskHasNoAssignedAgentError,
    TaskNotFoundError,
    TaskTransitionNotAllowedError,
)
from ..domain.models import Agent, AgentRun, AgentRunStatus, TaskSummary
from ..repository.agent_repository import AgentRepository
from ..repository.agent_run_repository import AgentRunRepository
from .agent_registry import AgentRegistry
from .run_events import RunEventBroker, RunEventPublisherAdapter
from .run_registry import RunRegistry

_SDK_TO_DB_STATUS = {
    SdkAgentRunStatus.COMPLETED: AgentRunStatus.SUCCEEDED,
    SdkAgentRunStatus.FAILED: AgentRunStatus.FAILED,
    SdkAgentRunStatus.CANCELLED: AgentRunStatus.CANCELLED,
}

# Same event type `_execute_and_persist()` publishes once its own commit lands — a client that
# subscribes only after a run already settled should see the identical terminal event a
# live-subscribed client would have seen, not a different name for the same fact.
_TERMINAL_STATUS_EVENT_TYPES = {
    AgentRunStatus.SUCCEEDED: "agent_run.persisted",
    AgentRunStatus.FAILED: "agent_run.persisted",
    AgentRunStatus.CANCELLED: "agent_run.persisted",
}


class AgentRunService:
    def __init__(
        self,
        agent_repository: AgentRepository,
        agent_run_repository: AgentRunRepository,
        task_service: TaskMemoryTaskService,
        context_builder_service: ContextBuilderService,
        agent_registry: AgentRegistry,
        run_registry: RunRegistry,
        run_event_broker: RunEventBroker,
    ) -> None:
        self._agents = agent_repository
        self._agent_runs = agent_run_repository
        self._tasks = task_service
        self._context_builder = context_builder_service
        self._agent_registry = agent_registry
        self._run_registry = run_registry
        self._run_event_broker = run_event_broker

    async def assign_agent(self, task_id: UUID, *, agent_id: UUID) -> TaskSummary:
        await self._get_task(task_id)
        agent = await self._agents.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)
        if not agent.is_enabled:
            raise AgentDisabledError(agent_id)
        updated = await self._tasks.assign_agent(task_id, agent_id=agent_id)
        return _to_task_summary(updated)

    async def start_run(
        self,
        task_id: UUID,
        *,
        provider: str,
        model_name: str,
        context_package_id: UUID,
    ) -> AgentRun:
        task = await self._get_task(task_id)
        if task.assigned_agent_id is None:
            raise TaskHasNoAssignedAgentError(task_id)
        agent = await self._agents.get_by_id(task.assigned_agent_id)
        if agent is None:
            raise AgentNotFoundError(task.assigned_agent_id)
        if not agent.is_enabled:
            raise AgentDisabledError(agent.id)

        try:
            context_package = await self._context_builder.get_context_package(context_package_id)
        except ContextBuilderContextPackageNotFoundError as exc:
            raise ContextPackageNotFoundError(context_package_id) from exc
        if context_package.task_id != task_id:
            raise ContextPackageNotFoundError(context_package_id)

        await self._transition_task(
            task_id, to_status=TaskMemoryTaskStatus.RUNNING, changed_by_agent_id=agent.id
        )

        agent_run = await self._agent_runs.add(
            AgentRun(
                id=uuid4(),
                agent_id=agent.id,
                task_id=task_id,
                context_package_id=context_package_id,
                provider=provider,
                model_name=model_name,
                status=AgentRunStatus.RUNNING,
                attempt_number=1,
                started_at=utcnow(),
            )
        )

        content = await self._context_builder.assemble_content(context_package_id)
        task_context = TaskContext(
            task_id=task_id, context_package_id=context_package_id, content=content
        )
        self._launch(agent, task_context, agent_run.id, attempt_number=1)
        return agent_run

    async def get_run(self, agent_run_id: UUID) -> AgentRun:
        run = await self._agent_runs.get_by_id(agent_run_id)
        if run is None:
            raise AgentRunNotFoundError(agent_run_id)
        return run

    async def list_runs_for_task(
        self, task_id: UUID, *, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[AgentRun], str | None, bool]:
        await self._get_task(task_id)
        return await self._agent_runs.list_for_task(task_id, cursor=cursor, limit=limit)

    async def cancel_run(self, agent_run_id: UUID) -> AgentRun:
        run = await self.get_run(agent_run_id)
        if run.status not in (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING):
            raise AgentRunNotCancellableError(agent_run_id)
        was_active = await self._run_registry.cancel(agent_run_id)
        if not was_active:
            raise AgentRunNotCancellableError(agent_run_id)
        return run  # cancellation is cooperative — the row updates once the run settles

    async def retry_run(self, agent_run_id: UUID) -> AgentRun:
        run = await self.get_run(agent_run_id)
        if run.status != AgentRunStatus.FAILED:
            raise AgentRunNotRetryableError(agent_run_id)
        agent = await self._agents.get_by_id(run.agent_id)
        if agent is None:
            raise AgentNotFoundError(run.agent_id)
        if not agent.is_enabled:
            raise AgentDisabledError(agent.id)

        # FAILED -> READY -> RUNNING: task_memory's state machine has no direct FAILED -> RUNNING
        # edge (retrying starts from the same "eligible to run" state a fresh task would).
        await self._transition_task(
            run.task_id, to_status=TaskMemoryTaskStatus.READY, changed_by_agent_id=agent.id
        )
        await self._transition_task(
            run.task_id, to_status=TaskMemoryTaskStatus.RUNNING, changed_by_agent_id=agent.id
        )

        next_attempt = run.attempt_number + 1
        run.status = AgentRunStatus.RUNNING
        run.attempt_number = next_attempt
        run.started_at = utcnow()
        run.completed_at = None
        run.error_message = None
        run = await self._agent_runs.update(run)

        content = ""
        if run.context_package_id is not None:
            content = await self._context_builder.assemble_content(run.context_package_id)
        task_context = TaskContext(
            task_id=run.task_id, context_package_id=run.context_package_id, content=content
        )
        self._launch(agent, task_context, run.id, attempt_number=next_attempt)
        return run

    async def subscribe_to_run_events(
        self, agent_run_id: UUID
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        run = await self.get_run(agent_run_id)  # 404 if the run never existed
        terminal_event_type = _TERMINAL_STATUS_EVENT_TYPES.get(run.status)
        if terminal_event_type is not None:
            # The run already settled — nothing will ever be published to the broker for it
            # again, so subscribing would hang forever. Synthesize the one terminal event from
            # its persisted final state instead.
            yield terminal_event_type, {
                "agent_run_id": str(run.id),
                "task_id": str(run.task_id),
                "status": run.status.value,
            }
            return
        async for event_type, payload in self._run_event_broker.subscribe(agent_run_id):
            yield event_type, payload

    # ---- internal helpers -------------------------------------------------------------------

    async def _get_task(self, task_id: UUID) -> TaskMemoryTask:
        try:
            return await self._tasks.get_task(task_id)
        except TaskMemoryTaskNotFoundError as exc:
            raise TaskNotFoundError(task_id) from exc

    async def _transition_task(
        self, task_id: UUID, *, to_status: TaskMemoryTaskStatus, changed_by_agent_id: UUID
    ) -> None:
        try:
            await self._tasks.transition_status(
                task_id, to_status=to_status, changed_by_agent_id=changed_by_agent_id
            )
        except TaskMemoryIllegalTransitionError as exc:
            raise TaskTransitionNotAllowedError(task_id, str(exc)) from exc
        except TaskMemoryUnmetDependenciesError as exc:
            raise TaskTransitionNotAllowedError(task_id, str(exc)) from exc

    def _launch(
        self,
        agent: Agent,
        task_context: TaskContext,
        agent_run_id: UUID,
        *,
        attempt_number: int,
    ) -> None:
        event_publisher = RunEventPublisherAdapter(self._run_event_broker, agent_run_id)
        agent_instance = self._agent_registry.create(
            agent.agent_type,
            agent_id=agent.id,
            version=agent.version,
            config=agent.config,
            event_publisher=event_publisher,
        )
        asyncio_task = asyncio.create_task(
            _execute_and_persist(
                agent_instance, task_context, agent_run_id, attempt_number, self._run_event_broker
            )
        )
        self._run_registry.track(agent_run_id, asyncio_task, agent_instance)
        asyncio_task.add_done_callback(lambda _: self._run_registry.untrack(agent_run_id))


async def _execute_and_persist(
    agent: BaseAgent,
    task_context: TaskContext,
    agent_run_id: UUID,
    attempt_number: int,
    run_event_broker: RunEventBroker,
) -> None:
    """Runs outside any HTTP request's scope — see this module's docstring for why it rebuilds
    its own session and calls `task_memory`/`projects`' `api/dependencies.py` provider functions
    directly instead of receiving already-built services from the request that launched it.

    `agent.run()` publishes its own terminal event (`agent_run.completed`/`failed`/`cancelled`)
    as the *last thing it does before returning* — i.e. strictly before this function's own DB
    write below even starts. A client watching the SSE stream would see that event and could
    immediately `GET /agent-runs/{runId}` expecting the persisted row to already reflect it,
    which — for the handful of milliseconds this function's own session/commit takes — it
    wouldn't yet. Publishing `agent_run.persisted` after the commit below, and treating *that* as
    the stream's true terminal signal (`run_events.py`'s `_TERMINAL_EVENT_TYPES`), closes that
    gap: by the time the stream ends, the row is guaranteed queryable in its final state.
    """
    report = await agent.run(task_context, agent_run_id=agent_run_id)

    session_factory = get_session_factory()
    async with session_factory() as session:
        agent_run_repository = AgentRunRepository(session)
        run = await agent_run_repository.get_by_id(agent_run_id)
        if run is None:  # pragma: no cover - defensive; the row is created before launching
            return

        run.status = _SDK_TO_DB_STATUS[report.agent_run_status]
        run.attempt_number = attempt_number
        run.completed_at = report.completed_at
        run.error_message = report.error
        if report.execution_result is not None:
            run.input_tokens = report.execution_result.input_tokens
            run.output_tokens = report.execution_result.output_tokens
            run.cost_usd = report.execution_result.cost_usd
        run = await agent_run_repository.update(run)

        feature_service = get_projects_feature_service(session=session)
        task_service = get_task_memory_task_service(
            session=session, projects_feature_service=feature_service
        )
        await _transition_task_after_run(task_service, run, report)

        await session.commit()

    await run_event_broker.publish(agent_run_id, "agent_run.persisted", {"status": run.status.value})


async def _transition_task_after_run(
    task_service: TaskMemoryTaskService, run: AgentRun, report: AgentReport
) -> None:
    if report.agent_run_status == SdkAgentRunStatus.FAILED:
        await task_service.transition_status(
            run.task_id, to_status=TaskMemoryTaskStatus.FAILED, changed_by_agent_id=run.agent_id
        )
        return
    if report.agent_run_status == SdkAgentRunStatus.CANCELLED:
        await task_service.transition_status(
            run.task_id, to_status=TaskMemoryTaskStatus.CANCELLED, changed_by_agent_id=run.agent_id
        )
        return

    # COMPLETED: the SDK's cheap SelfEvaluation stands in for the (not yet built) Evaluation
    # Framework's authoritative quality gate — see this module's README's "Known gaps".
    await task_service.transition_status(
        run.task_id, to_status=TaskMemoryTaskStatus.EVALUATING, changed_by_agent_id=run.agent_id
    )
    passed = report.self_evaluation.passed if report.self_evaluation is not None else False
    next_status = (
        TaskMemoryTaskStatus.AWAITING_APPROVAL if passed else TaskMemoryTaskStatus.FAILED
    )
    await task_service.transition_status(
        run.task_id, to_status=next_status, changed_by_agent_id=run.agent_id
    )


def _to_task_summary(task: TaskMemoryTask) -> TaskSummary:
    return TaskSummary(
        id=task.id,
        status=task.status.value,
        assigned_agent_id=task.assigned_agent_id,
        updated_at=task.updated_at,
    )
