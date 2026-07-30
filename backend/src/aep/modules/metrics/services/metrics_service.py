"""Use-case orchestration for the Metrics Service (docs/architecture/04-api-design.md §9).

**Read-only public HTTP surface, one internal write path**: per the API design doc's own framing
("writes happen internally as agents/evaluations complete"), `record_metric()` has no HTTP
endpoint — it's this module's public `services/` surface for *other* modules to call into, the
same pattern as `auth.AuditService.record_event()`. No module currently calls it (recording
metrics from `orchestrator`'s/`evaluation`'s completion paths is a follow-up, not attempted here
as a retrofit — see this module's README), so this reference implementation's aggregation
endpoints are real and tested against data written directly through this service, but return
empty results against the rest of this codebase's actual traffic until that wiring exists.

**`group_by=provider` is not supported.** The API design doc's `group_by` enum lists
`project|agent|provider|day`, but `metrics.entity_type`/`entity_id` (DB design §18) is a single
polymorphic reference per row — there's no table of "providers" with their own UUIDs to point
`entity_id` at, unlike `project`/`agent` which map onto real rows elsewhere in the schema.
Requesting it raises `UnsupportedGroupByError`, translated to a 422 by `api/router.py` — the
same status code the API design doc already specifies for "group_by/agg not in the allowed set."

**`p95` is computed in Python, not pushed down to SQL.** SQLite (this project's test backend)
has no percentile function at all; Postgres (production) has `percentile_cont`, but relying on
it would mean `sum`/`avg` and `p95` take genuinely different code paths for "the same kind of
number." Every aggregation here fetches raw values per bucket and reduces them in Python —
correct, but not what a production deployment would want once `metrics` grows large enough to
need the partitioning the DB design doc's own "Operational note" (§18) already flags.
"""

from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID, uuid4

from aep.modules.projects.domain.errors import (
    ProjectNotFoundError as ProjectsProjectNotFoundError,
)
from aep.modules.projects.services import ProjectService as ProjectsProjectService

from ..domain.errors import (
    ProjectNotFoundError,
    UnsupportedAggregationError,
    UnsupportedGroupByError,
)
from ..domain.models import (
    Metric,
    MetricSummary,
    MetricSummaryBucket,
    ProjectMetricRollupEntry,
    ProjectMetricsSummary,
)
from ..repository.metric_repository import MetricRepository

_SUPPORTED_GROUP_BY = {"day", "project", "agent"}
_SUPPORTED_AGG = {"sum", "avg", "p95"}


class MetricsService:
    def __init__(
        self, metric_repository: MetricRepository, project_service: ProjectsProjectService
    ) -> None:
        self._metrics = metric_repository
        self._projects = project_service

    async def record_metric(
        self,
        *,
        metric_name: str,
        entity_type: str,
        entity_id: UUID,
        value: float,
        unit: str | None = None,
    ) -> Metric:
        return await self._metrics.add(
            Metric(
                id=uuid4(),
                metric_name=metric_name,
                entity_type=entity_type,
                entity_id=entity_id,
                value=value,
                unit=unit,
            )
        )

    async def list_metrics(
        self,
        *,
        metric_name: str,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        recorded_at_from: datetime | None = None,
        recorded_at_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Metric], str | None, bool]:
        return await self._metrics.list_for_query(
            metric_name=metric_name,
            entity_type=entity_type,
            entity_id=entity_id,
            recorded_at_from=recorded_at_from,
            recorded_at_to=recorded_at_to,
            cursor=cursor,
            limit=limit,
        )

    async def get_summary(
        self,
        *,
        metric_name: str,
        group_by: str,
        agg: str,
        recorded_at_from: datetime | None = None,
        recorded_at_to: datetime | None = None,
    ) -> MetricSummary:
        if agg not in _SUPPORTED_AGG:
            raise UnsupportedAggregationError(agg)
        if group_by not in _SUPPORTED_GROUP_BY:
            raise UnsupportedGroupByError(group_by)

        if group_by == "day":
            grouped = await self._metrics.list_values_grouped_by_day(
                metric_name=metric_name,
                recorded_at_from=recorded_at_from,
                recorded_at_to=recorded_at_to,
            )
        else:
            grouped = await self._metrics.list_values_grouped_by_entity(
                metric_name=metric_name,
                entity_type=group_by,
                recorded_at_from=recorded_at_from,
                recorded_at_to=recorded_at_to,
            )

        buckets = [
            MetricSummaryBucket(key=key, value=_aggregate(values, agg))
            for key, values in sorted(grouped.items())
        ]
        return MetricSummary(metric_name=metric_name, group_by=group_by, agg=agg, buckets=buckets)

    async def get_project_summary(
        self,
        project_id: UUID,
        *,
        recorded_at_from: datetime | None = None,
        recorded_at_to: datetime | None = None,
    ) -> ProjectMetricsSummary:
        try:
            await self._projects.get_project(project_id)
        except ProjectsProjectNotFoundError as exc:
            raise ProjectNotFoundError(project_id) from exc

        grouped = await self._metrics.list_values_grouped_by_metric_name(
            entity_type="project",
            entity_id=project_id,
            recorded_at_from=recorded_at_from,
            recorded_at_to=recorded_at_to,
        )
        entries = [
            ProjectMetricRollupEntry(
                metric_name=name, sum=sum(values), avg=sum(values) / len(values), count=len(values)
            )
            for name, values in sorted(grouped.items())
        ]
        return ProjectMetricsSummary(project_id=project_id, metrics=entries)


def _aggregate(values: list[float], agg: str) -> float:
    if agg == "sum":
        return sum(values)
    if agg == "avg":
        return sum(values) / len(values) if values else 0.0
    return _percentile(values, 0.95)  # agg == "p95", already validated by the caller


def _percentile(values: list[float], p: float) -> float:
    """Nearest-rank method — simple and well-defined, not the only valid choice (linear
    interpolation is common too), but a reasonable one for a reference implementation."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, max(0, math.ceil(p * len(sorted_values)) - 1))
    return sorted_values[index]
