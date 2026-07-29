"""Domain-level errors for the Context Builder — pure Python, no framework imports, and no
dependency on `core/errors.py`'s HTTP-mapped `AEPError` hierarchy either: the `api/` layer is
the sole translation boundary between these and an HTTP response
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID


class ContextBuilderDomainError(Exception):
    """Base class for every Context Builder domain error."""


class TaskNotFoundError(ContextBuilderDomainError):
    """Raised when the task a context package is requested for doesn't exist. This module's own
    local equivalent of `aep.modules.task_memory.domain.errors.TaskNotFoundError` — translated at
    the `services/` boundary, same pattern as `task_memory`'s own translation of Project Service's
    `FeatureNotFoundError` (see that module's README)."""

    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"task {task_id} not found")
        self.task_id = task_id


class FeatureNotFoundError(ContextBuilderDomainError):
    """This module's local equivalent of the Project Service's `FeatureNotFoundError`, raised
    when a task's `feature_id` can't be resolved to a real feature (used to look up the task's
    `project_id`)."""

    def __init__(self, feature_id: UUID) -> None:
        super().__init__(f"feature {feature_id} not found")
        self.feature_id = feature_id


class ProjectNotFoundError(ContextBuilderDomainError):
    """This module's local equivalent of the Project Service's `ProjectNotFoundError`, raised
    when listing source documents for a project that doesn't exist."""

    def __init__(self, project_id: UUID) -> None:
        super().__init__(f"project {project_id} not found")
        self.project_id = project_id


class ContextPackageNotFoundError(ContextBuilderDomainError):
    def __init__(self, context_package_id: UUID) -> None:
        super().__init__(f"context package {context_package_id} not found")
        self.context_package_id = context_package_id
