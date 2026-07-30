"""Pure domain entities and value objects for the Metrics Service
(docs/architecture/03-db-design.md §18; docs/architecture/04-api-design.md §9;
docs/architecture/02-repo-design.md §2's domain/ layer — zero framework imports).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

# Not typed as a `Literal` here: the API design doc's own `group_by` enum includes `provider`,
# which this reference implementation deliberately doesn't support (see `services/README` /
# `MetricsService`'s docstring) — the *service* validates and raises a clear domain error for
# it, rather than the type system silently narrowing it away before that error can be
# constructed with a helpful message.
GroupBy = str
Aggregation = str


@dataclass
class Metric:
    """One row of `metrics` (DB design §18) — `entity_type`/`entity_id` are polymorphic by
    design, same convention as `audit_events`."""

    id: UUID
    metric_name: str
    entity_type: str
    entity_id: UUID
    value: float
    unit: str | None = None
    recorded_at: datetime | None = None


@dataclass
class MetricSummaryBucket:
    key: str
    value: float


@dataclass
class MetricSummary:
    """docs/architecture/04-api-design.md §9's `GET /metrics/summary` response, computed on
    read — never persisted, same "aggregation is a query, not a stored fact" stance as
    `evaluation`'s quality gate."""

    metric_name: str
    group_by: GroupBy
    agg: Aggregation
    buckets: list[MetricSummaryBucket] = field(default_factory=list)


@dataclass
class ProjectMetricRollupEntry:
    metric_name: str
    sum: float
    avg: float
    count: int


@dataclass
class ProjectMetricsSummary:
    """`GET /projects/{projectId}/metrics/summary`'s response — one rollup entry per distinct
    `metric_name` recorded against this project."""

    project_id: UUID
    metrics: list[ProjectMetricRollupEntry] = field(default_factory=list)
