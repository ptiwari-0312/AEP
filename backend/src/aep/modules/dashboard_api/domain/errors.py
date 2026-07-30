"""Domain-level errors for the Dashboard API — pure Python, no framework imports, and no
dependency on `core/errors.py`'s HTTP-mapped `AEPError` hierarchy either: the `api/` layer is the
sole translation boundary between these and an HTTP response
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID


class DashboardDomainError(Exception):
    """Base class for every Dashboard API domain error."""


class ProjectNotFoundError(DashboardDomainError):
    """This module's local equivalent of `projects.domain.errors.ProjectNotFoundError`."""

    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"project {project_id} not found")
        self.project_id = project_id
