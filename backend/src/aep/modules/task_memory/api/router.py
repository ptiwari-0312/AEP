"""FastAPI routers for the Task Memory Service (docs/architecture/04-api-design.md §3). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here — the
sole boundary where that translation happens (docs/architecture/09-engineering-standards.md §6).

`POST /features/{featureId}/task-graph:generate` is deliberately not implemented — it requires
the Agent Orchestrator and a PlannerAgent invocation, neither of which exist in `backend/` yet.
A stub returning `202` would be actively misleading (a caller polling `job_id` would wait
forever); omitting the endpoint until it's real is the honest choice.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from aep.core.errors import ConflictError, NotFoundError

from ..domain.errors import (
    CyclicDependencyError,
    DuplicateDependencyError,
    FeatureNotFoundError,
    IllegalTaskStatusTransitionError,
    SelfDependencyError,
    TaskDependencyNotFoundError,
    TaskNotFoundError,
    UnmetDependenciesError,
)
from ..domain.models import Task, TaskStatus, TaskType
from ..services.task_service import TaskService
from .dependencies import get_current_user_id, get_task_service
from .schemas import (
    ExecutionHistoryEntryResponse,
    ExecutionHistoryListResponse,
    TaskCreateRequest,
    TaskDependencyCreateRequest,
    TaskDependencyResponse,
    TaskListResponse,
    TaskResponse,
    TaskStatusTransitionRequest,
    TaskUpdateRequest,
)

router = APIRouter(prefix="/api/v1", tags=["task-memory"])


async def _to_task_response(task: Task, service: TaskService) -> TaskResponse:
    dependencies = await service.list_dependencies(task.id)
    response = TaskResponse.model_validate(task)
    return response.model_copy(update={"depends_on": [d.depends_on_task_id for d in dependencies]})


@router.post("/features/{feature_id}/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    feature_id: UUID,
    request: TaskCreateRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    try:
        task = await service.create_task(
            feature_id=feature_id,
            title=request.title,
            task_type=request.task_type,
            description=request.description,
            priority=request.priority,
        )
    except FeatureNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return await _to_task_response(task, service)


@router.get("/features/{feature_id}/tasks", response_model=TaskListResponse)
async def list_tasks(
    feature_id: UUID,
    service: TaskService = Depends(get_task_service),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    task_type: TaskType | None = Query(default=None),
    assigned_agent_id: UUID | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> TaskListResponse:
    try:
        tasks, next_cursor, has_more = await service.list_tasks_for_feature(
            feature_id,
            status=status_filter,
            task_type=task_type,
            assigned_agent_id=assigned_agent_id,
            cursor=cursor,
            limit=limit,
        )
    except FeatureNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    items = [await _to_task_response(task, service) for task in tasks]
    return TaskListResponse(items=items, next_cursor=next_cursor, has_more=has_more)


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: UUID, service: TaskService = Depends(get_task_service)) -> TaskResponse:
    try:
        task = await service.get_task(task_id)
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return await _to_task_response(task, service)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID, request: TaskUpdateRequest, service: TaskService = Depends(get_task_service)
) -> TaskResponse:
    try:
        task = await service.update_task(
            task_id, title=request.title, description=request.description, priority=request.priority
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return await _to_task_response(task, service)


@router.post("/tasks/{task_id}/status", response_model=TaskResponse)
async def transition_task_status(
    task_id: UUID,
    request: TaskStatusTransitionRequest,
    service: TaskService = Depends(get_task_service),
    changed_by_user_id: UUID = Depends(get_current_user_id),
) -> TaskResponse:
    try:
        task = await service.transition_status(
            task_id,
            to_status=request.to_status,
            reason=request.reason,
            changed_by_user_id=changed_by_user_id,
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except (IllegalTaskStatusTransitionError, UnmetDependenciesError) as exc:
        raise ConflictError(str(exc)) from exc
    return await _to_task_response(task, service)


@router.post("/tasks/{task_id}/dependencies", response_model=TaskDependencyResponse, status_code=201)
async def add_dependency(
    task_id: UUID,
    request: TaskDependencyCreateRequest,
    service: TaskService = Depends(get_task_service),
) -> TaskDependencyResponse:
    try:
        dependency = await service.add_dependency(
            task_id,
            depends_on_task_id=request.depends_on_task_id,
            dependency_type=request.dependency_type,
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except (SelfDependencyError, DuplicateDependencyError, CyclicDependencyError) as exc:
        raise ConflictError(str(exc)) from exc
    return TaskDependencyResponse.model_validate(dependency)


@router.delete("/tasks/{task_id}/dependencies/{dependency_id}", status_code=204)
async def remove_dependency(
    task_id: UUID, dependency_id: UUID, service: TaskService = Depends(get_task_service)
) -> None:
    try:
        await service.remove_dependency(dependency_id)
    except TaskDependencyNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc


@router.get("/tasks/{task_id}/execution-history", response_model=ExecutionHistoryListResponse)
async def list_execution_history(
    task_id: UUID,
    service: TaskService = Depends(get_task_service),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> ExecutionHistoryListResponse:
    try:
        entries, next_cursor, has_more = await service.list_execution_history(
            task_id, cursor=cursor, limit=limit
        )
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    items = [ExecutionHistoryEntryResponse.model_validate(entry) for entry in entries]
    return ExecutionHistoryListResponse(items=items, next_cursor=next_cursor, has_more=has_more)
