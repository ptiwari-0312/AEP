"""Context Builder domain layer — entities, value objects, and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import (
    ContextBuilderDomainError,
    ContextPackageNotFoundError,
    FeatureNotFoundError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from .models import (
    ContextPackage,
    ContextPackageSource,
    RankingWeights,
    SourceDocument,
    SourceDocumentType,
)

__all__ = [
    "ContextBuilderDomainError",
    "ContextPackage",
    "ContextPackageNotFoundError",
    "ContextPackageSource",
    "FeatureNotFoundError",
    "ProjectNotFoundError",
    "RankingWeights",
    "SourceDocument",
    "SourceDocumentType",
    "TaskNotFoundError",
]
