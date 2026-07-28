"""Project Service domain layer — entities, value objects, and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import (
    FeatureNotFoundError,
    IllegalFeatureStatusTransitionError,
    ProjectAlreadyArchivedError,
    ProjectDomainError,
    ProjectNotFoundError,
    SlugAlreadyExistsError,
)
from .models import (
    Feature,
    FeatureStatus,
    GitRepository,
    Project,
    ProjectStatus,
    is_legal_feature_transition,
)

__all__ = [
    "Feature",
    "FeatureNotFoundError",
    "FeatureStatus",
    "GitRepository",
    "IllegalFeatureStatusTransitionError",
    "Project",
    "ProjectAlreadyArchivedError",
    "ProjectDomainError",
    "ProjectNotFoundError",
    "ProjectStatus",
    "SlugAlreadyExistsError",
    "is_legal_feature_transition",
]
