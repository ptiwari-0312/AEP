"""Dashboard API domain layer — read-model DTOs and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import DashboardDomainError, ProjectNotFoundError
from .models import (
    DashboardOverview,
    RecentAuditEventSummary,
    RecentEvaluationSummary,
    RunningAgentSummary,
    TaskGraph,
    TaskGraphEdge,
    TaskGraphNode,
)

__all__ = [
    "DashboardDomainError",
    "DashboardOverview",
    "ProjectNotFoundError",
    "RecentAuditEventSummary",
    "RecentEvaluationSummary",
    "RunningAgentSummary",
    "TaskGraph",
    "TaskGraphEdge",
    "TaskGraphNode",
]
