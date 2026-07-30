"""Domain-level errors for the Metrics Service — pure Python, no framework imports, and no
dependency on `core/errors.py`'s HTTP-mapped `AEPError` hierarchy either: the `api/` layer is the
sole translation boundary between these and an HTTP response
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID


class MetricsDomainError(Exception):
    """Base class for every Metrics Service domain error."""


class UnsupportedGroupByError(MetricsDomainError):
    """Raised for a `group_by` value the API design doc lists but this reference implementation
    doesn't support (`provider`) — see `services/metrics_service.py`'s docstring for why."""

    def __init__(self, group_by: str) -> None:
        super().__init__(
            f"group_by={group_by!r} is not supported by this reference implementation"
        )
        self.group_by = group_by


class UnsupportedAggregationError(MetricsDomainError):
    def __init__(self, agg: str) -> None:
        super().__init__(f"agg={agg!r} is not a supported aggregation")
        self.agg = agg


class ProjectNotFoundError(MetricsDomainError):
    """This module's local equivalent of `projects.domain.errors.ProjectNotFoundError`."""

    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"project {project_id} not found")
        self.project_id = project_id
