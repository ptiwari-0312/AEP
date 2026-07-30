"""FastAPI routers for the Agent Orchestrator (docs/architecture/04-api-design.md §5). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here — the
sole boundary where that translation happens (docs/architecture/09-engineering-standards.md §6);
`domain/` and `services/` know nothing about HTTP.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from aep.core.errors import ConflictError, NotFoundError

from ..domain.errors import (
    AgentDisabledError,
    AgentNameVersionExistsError,
    AgentNotFoundError,
    AgentRunNotCancellableError,
    AgentRunNotFoundError,
    AgentRunNotRetryableError,
    ContextPackageNotFoundError,
    TaskHasNoAssignedAgentError,
    TaskNotFoundError,
    TaskTransitionNotAllowedError,
)
from ..domain.models import AgentType
from ..services.agent_run_service import AgentRunService
from ..services.agent_service import AgentService
from ..services.task_review_service import TaskReviewService
from .dependencies import (
    get_agent_run_service,
    get_agent_service,
    get_current_user_id,
    get_task_review_service,
)
from .schemas import (
    AgentListResponse,
    AgentRegisterRequest,
    AgentResponse,
    AgentRunListResponse,
    AgentRunResponse,
    AgentUpdateRequest,
    ApproveTaskRequest,
    AssignAgentRequest,
    RejectTaskRequest,
    StartRunRequest,
    StartRunResponse,
    TaskSummaryResponse,
)

router = APIRouter(prefix="/api/v1", tags=["orchestrator"])


# ---- Agents -------------------------------------------------------------------------------


@router.post("/agents", response_model=AgentResponse, status_code=201)
async def register_agent(
    request: AgentRegisterRequest,
    service: AgentService = Depends(get_agent_service),
    _user_id: UUID = Depends(get_current_user_id),
) -> AgentResponse:
    try:
        agent = await service.register_agent(
            name=request.name,
            agent_type=request.agent_type,
            version=request.version,
            config=request.config,
        )
    except AgentNameVersionExistsError as exc:
        raise ConflictError(str(exc)) from exc
    return AgentResponse.model_validate(agent)


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    service: AgentService = Depends(get_agent_service),
    agent_type: AgentType | None = Query(default=None),
    is_enabled: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AgentListResponse:
    agents, total = await service.list_agents(
        agent_type=agent_type,
        is_enabled=is_enabled,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return AgentListResponse(
        items=[AgentResponse.model_validate(a) for a in agents],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID, service: AgentService = Depends(get_agent_service)
) -> AgentResponse:
    try:
        agent = await service.get_agent(agent_id)
    except AgentNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return AgentResponse.model_validate(agent)


@router.patch("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    request: AgentUpdateRequest,
    service: AgentService = Depends(get_agent_service),
) -> AgentResponse:
    try:
        agent = await service.update_agent(
            agent_id, is_enabled=request.is_enabled, config=request.config
        )
    except AgentNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return AgentResponse.model_validate(agent)


# ---- Assignment & runs ---------------------------------------------------------------------


@router.post("/tasks/{task_id}/assign", response_model=TaskSummaryResponse)
async def assign_agent(
    task_id: UUID,
    request: AssignAgentRequest,
    service: AgentRunService = Depends(get_agent_run_service),
) -> TaskSummaryResponse:
    try:
        summary = await service.assign_agent(task_id, agent_id=request.agent_id)
    except (TaskNotFoundError, AgentNotFoundError) as exc:
        raise NotFoundError(str(exc)) from exc
    except AgentDisabledError as exc:
        raise ConflictError(str(exc)) from exc
    return TaskSummaryResponse.model_validate(summary)


@router.post("/tasks/{task_id}/runs", response_model=StartRunResponse, status_code=202)
async def start_run(
    task_id: UUID,
    request: StartRunRequest,
    service: AgentRunService = Depends(get_agent_run_service),
) -> StartRunResponse:
    try:
        agent_run = await service.start_run(
            task_id,
            provider=request.provider,
            model_name=request.model_name,
            context_package_id=request.context_package_id,
        )
    except (TaskNotFoundError, AgentNotFoundError, ContextPackageNotFoundError) as exc:
        raise NotFoundError(str(exc)) from exc
    except (AgentDisabledError, TaskHasNoAssignedAgentError, TaskTransitionNotAllowedError) as exc:
        raise ConflictError(str(exc)) from exc
    return StartRunResponse(agent_run_id=str(agent_run.id))


@router.get("/tasks/{task_id}/runs", response_model=AgentRunListResponse)
async def list_runs(
    task_id: UUID,
    service: AgentRunService = Depends(get_agent_run_service),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> AgentRunListResponse:
    try:
        runs, next_cursor, has_more = await service.list_runs_for_task(
            task_id, cursor=cursor, limit=limit
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return AgentRunListResponse(
        items=[AgentRunResponse.model_validate(r) for r in runs],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/agent-runs/{run_id}", response_model=AgentRunResponse)
async def get_run(
    run_id: UUID, service: AgentRunService = Depends(get_agent_run_service)
) -> AgentRunResponse:
    try:
        run = await service.get_run(run_id)
    except AgentRunNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return AgentRunResponse.model_validate(run)


@router.post("/agent-runs/{run_id}/cancel", response_model=AgentRunResponse)
async def cancel_run(
    run_id: UUID, service: AgentRunService = Depends(get_agent_run_service)
) -> AgentRunResponse:
    try:
        run = await service.cancel_run(run_id)
    except AgentRunNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except AgentRunNotCancellableError as exc:
        raise ConflictError(str(exc)) from exc
    return AgentRunResponse.model_validate(run)


@router.post("/agent-runs/{run_id}/retry", response_model=AgentRunResponse, status_code=202)
async def retry_run(
    run_id: UUID, service: AgentRunService = Depends(get_agent_run_service)
) -> AgentRunResponse:
    try:
        run = await service.retry_run(run_id)
    except (AgentRunNotFoundError, AgentNotFoundError) as exc:
        raise NotFoundError(str(exc)) from exc
    except (AgentRunNotRetryableError, AgentDisabledError, TaskTransitionNotAllowedError) as exc:
        raise ConflictError(str(exc)) from exc
    return AgentRunResponse.model_validate(run)


@router.get("/agent-runs/{run_id}/events")
async def stream_run_events(
    run_id: UUID, service: AgentRunService = Depends(get_agent_run_service)
) -> StreamingResponse:
    try:
        await service.get_run(run_id)
    except AgentRunNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc

    async def _event_stream() -> AsyncIterator[str]:
        async for event_type, payload in service.subscribe_to_run_events(run_id):
            yield f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


# ---- Human approval gate --------------------------------------------------------------------


@router.post("/tasks/{task_id}/approve", response_model=TaskSummaryResponse)
async def approve_task(
    task_id: UUID,
    request: ApproveTaskRequest,
    service: TaskReviewService = Depends(get_task_review_service),
    reviewer_user_id: UUID = Depends(get_current_user_id),
) -> TaskSummaryResponse:
    try:
        summary = await service.approve(
            task_id, reviewer_user_id=reviewer_user_id, comment=request.comment
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except TaskTransitionNotAllowedError as exc:
        raise ConflictError(str(exc)) from exc
    return TaskSummaryResponse.model_validate(summary)


@router.post("/tasks/{task_id}/reject", response_model=TaskSummaryResponse)
async def reject_task(
    task_id: UUID,
    request: RejectTaskRequest,
    service: TaskReviewService = Depends(get_task_review_service),
    reviewer_user_id: UUID = Depends(get_current_user_id),
) -> TaskSummaryResponse:
    try:
        summary = await service.reject(
            task_id, reviewer_user_id=reviewer_user_id, comment=request.comment
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except TaskTransitionNotAllowedError as exc:
        raise ConflictError(str(exc)) from exc
    return TaskSummaryResponse.model_validate(summary)


@router.post("/tasks/{task_id}/merge", response_model=TaskSummaryResponse)
async def merge_task(
    task_id: UUID,
    service: TaskReviewService = Depends(get_task_review_service),
    actor_user_id: UUID = Depends(get_current_user_id),
) -> TaskSummaryResponse:
    try:
        summary = await service.merge(task_id, actor_user_id=actor_user_id)
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except TaskTransitionNotAllowedError as exc:
        raise ConflictError(str(exc)) from exc
    return TaskSummaryResponse.model_validate(summary)
