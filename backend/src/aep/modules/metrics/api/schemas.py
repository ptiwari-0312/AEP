"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §9 —
no DB calls in this layer (docs/architecture/02-repo-design.md §2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# All four literals the API design doc names, even though `group_by="provider"` is rejected by
# the service with a clear domain error (see `services/metrics_service.py`) rather than being
# excluded here — a 422 either way, but with a more specific message than a bare schema mismatch.
GroupByLiteral = Literal["project", "agent", "provider", "day"]
AggregationLiteral = Literal["sum", "avg", "p95"]


class MetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    entity_type: str
    entity_id: UUID
    value: float
    unit: str | None
    recorded_at: datetime | None


class MetricListResponse(BaseModel):
    items: list[MetricResponse]
    next_cursor: str | None
    has_more: bool


class MetricSummaryBucketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: float


class MetricSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    group_by: str
    agg: str
    buckets: list[MetricSummaryBucketResponse]


class ProjectMetricRollupEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    sum: float
    avg: float
    count: int


class ProjectMetricsSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    metrics: list[ProjectMetricRollupEntryResponse]
