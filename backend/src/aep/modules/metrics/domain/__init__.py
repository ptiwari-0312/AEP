"""Metrics Service domain layer — entities, value objects, and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import (
    MetricsDomainError,
    ProjectNotFoundError,
    UnsupportedAggregationError,
    UnsupportedGroupByError,
)
from .models import (
    Aggregation,
    GroupBy,
    Metric,
    MetricSummary,
    MetricSummaryBucket,
    ProjectMetricRollupEntry,
    ProjectMetricsSummary,
)

__all__ = [
    "Aggregation",
    "GroupBy",
    "Metric",
    "MetricSummary",
    "MetricSummaryBucket",
    "MetricsDomainError",
    "ProjectMetricRollupEntry",
    "ProjectMetricsSummary",
    "ProjectNotFoundError",
    "UnsupportedAggregationError",
    "UnsupportedGroupByError",
]
