"""Domain-level errors for the Project Service — pure Python, no framework imports, and no
dependency on `core/errors.py`'s HTTP-mapped `AEPError` hierarchy either: the `api/` layer is
the sole translation boundary between these and an HTTP response
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID

from .models import FeatureStatus


class ProjectDomainError(Exception):
    """Base class for every Project Service domain error."""


class SlugAlreadyExistsError(ProjectDomainError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"a project with slug {slug!r} already exists")
        self.slug = slug


class ProjectNotFoundError(ProjectDomainError):
    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"project {project_id} not found")
        self.project_id = project_id


class ProjectAlreadyArchivedError(ProjectDomainError):
    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"project {project_id} is already archived")
        self.project_id = project_id


class FeatureNotFoundError(ProjectDomainError):
    def __init__(self, feature_id: UUID) -> None:
        super().__init__(f"feature {feature_id} not found")
        self.feature_id = feature_id


class IllegalFeatureStatusTransitionError(ProjectDomainError):
    def __init__(self, current: FeatureStatus, target: FeatureStatus) -> None:
        super().__init__(f"cannot transition feature from {current.value!r} to {target.value!r}")
        self.current = current
        self.target = target
