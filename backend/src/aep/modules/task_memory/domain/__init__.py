"""Task Memory Service domain layer — entities, value objects, and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import (
    CyclicDependencyError,
    DuplicateDependencyError,
    FeatureNotFoundError,
    IllegalTaskStatusTransitionError,
    SelfDependencyError,
    TaskDependencyNotFoundError,
    TaskDomainError,
    TaskNotFoundError,
    UnmetDependenciesError,
)
from .models import (
    DependencyType,
    ExecutionHistoryEntry,
    Task,
    TaskDependency,
    TaskStatus,
    TaskType,
    is_legal_task_transition,
    requires_dependencies_satisfied,
)

__all__ = [
    "CyclicDependencyError",
    "DependencyType",
    "DuplicateDependencyError",
    "ExecutionHistoryEntry",
    "FeatureNotFoundError",
    "IllegalTaskStatusTransitionError",
    "SelfDependencyError",
    "Task",
    "TaskDependency",
    "TaskDependencyNotFoundError",
    "TaskDomainError",
    "TaskNotFoundError",
    "TaskStatus",
    "TaskType",
    "UnmetDependenciesError",
    "is_legal_task_transition",
    "requires_dependencies_satisfied",
]
