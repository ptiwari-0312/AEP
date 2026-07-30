"""FastAPI routers for the Dashboard API (docs/architecture/04-api-design.md §11). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here — the
sole boundary where that translation happens (docs/architecture/09-engineering-standards.md §6);
`domain/` and `services/` know nothing about HTTP.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from aep.core.errors import NotFoundError

from ..domain.errors import ProjectNotFoundError
from ..services.dashboard_service import DashboardService
from .dependencies import get_current_user_id, get_dashboard_service
from .schemas import DashboardOverviewResponse, RunningAgentResponse, TaskGraphResponse

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_overview(
    service: DashboardService = Depends(get_dashboard_service),
    _user_id: UUID = Depends(get_current_user_id),
) -> DashboardOverviewResponse:
    overview = await service.get_overview()
    return DashboardOverviewResponse.model_validate(overview)


@router.get("/projects/{project_id}/task-graph", response_model=TaskGraphResponse)
async def get_task_graph(
    project_id: UUID,
    service: DashboardService = Depends(get_dashboard_service),
    _user_id: UUID = Depends(get_current_user_id),
) -> TaskGraphResponse:
    try:
        graph = await service.get_task_graph(project_id)
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return TaskGraphResponse.model_validate(graph)


@router.get("/running-agents", response_model=list[RunningAgentResponse])
async def list_running_agents(
    service: DashboardService = Depends(get_dashboard_service),
    _user_id: UUID = Depends(get_current_user_id),
) -> list[RunningAgentResponse]:
    running_agents = await service.list_running_agents()
    return [RunningAgentResponse.model_validate(r) for r in running_agents]
