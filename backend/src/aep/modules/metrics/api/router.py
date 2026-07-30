"""FastAPI routers for the Metrics Service (docs/architecture/04-api-design.md §9). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here — the
sole boundary where that translation happens (docs/architecture/09-engineering-standards.md §6);
`domain/` and `services/` know nothing about HTTP.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from aep.core.errors import NotFoundError, ValidationFailedError

from ..domain.errors import (
    ProjectNotFoundError,
    UnsupportedAggregationError,
    UnsupportedGroupByError,
)
from ..services.metrics_service import MetricsService
from .dependencies import get_current_user_id, get_metrics_service
from .schemas import (
    AggregationLiteral,
    GroupByLiteral,
    MetricListResponse,
    MetricResponse,
    MetricSummaryResponse,
    ProjectMetricsSummaryResponse,
)

router = APIRouter(prefix="/api/v1", tags=["metrics"])


@router.get("/metrics", response_model=MetricListResponse)
async def list_metrics(
    service: MetricsService = Depends(get_metrics_service),
    _user_id: UUID = Depends(get_current_user_id),
    metric_name: str = Query(...),
    entity_type: str | None = Query(default=None),
    entity_id: UUID | None = Query(default=None),
    recorded_at_from: datetime | None = Query(default=None),
    recorded_at_to: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> MetricListResponse:
    metrics, next_cursor, has_more = await service.list_metrics(
        metric_name=metric_name,
        entity_type=entity_type,
        entity_id=entity_id,
        recorded_at_from=recorded_at_from,
        recorded_at_to=recorded_at_to,
        cursor=cursor,
        limit=limit,
    )
    return MetricListResponse(
        items=[MetricResponse.model_validate(m) for m in metrics],
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/metrics/summary", response_model=MetricSummaryResponse)
async def get_metrics_summary(
    service: MetricsService = Depends(get_metrics_service),
    _user_id: UUID = Depends(get_current_user_id),
    metric_name: str = Query(...),
    group_by: GroupByLiteral = Query(...),
    agg: AggregationLiteral = Query(default="sum"),
    recorded_at_from: datetime | None = Query(default=None),
    recorded_at_to: datetime | None = Query(default=None),
) -> MetricSummaryResponse:
    try:
        summary = await service.get_summary(
            metric_name=metric_name,
            group_by=group_by,
            agg=agg,
            recorded_at_from=recorded_at_from,
            recorded_at_to=recorded_at_to,
        )
    except UnsupportedGroupByError as exc:
        raise ValidationFailedError(
            str(exc), errors=[{"field": "group_by", "message": str(exc)}]
        ) from exc
    except UnsupportedAggregationError as exc:
        raise ValidationFailedError(str(exc), errors=[{"field": "agg", "message": str(exc)}]) from exc
    return MetricSummaryResponse.model_validate(summary)


@router.get(
    "/projects/{project_id}/metrics/summary", response_model=ProjectMetricsSummaryResponse
)
async def get_project_metrics_summary(
    project_id: UUID,
    service: MetricsService = Depends(get_metrics_service),
    _user_id: UUID = Depends(get_current_user_id),
    recorded_at_from: datetime | None = Query(default=None),
    recorded_at_to: datetime | None = Query(default=None),
) -> ProjectMetricsSummaryResponse:
    try:
        summary = await service.get_project_summary(
            project_id, recorded_at_from=recorded_at_from, recorded_at_to=recorded_at_to
        )
    except ProjectNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return ProjectMetricsSummaryResponse.model_validate(summary)
