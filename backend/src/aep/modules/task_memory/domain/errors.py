"""Domain-level errors for the Task Memory Service — pure Python, no framework imports."""

from __future__ import annotations

from uuid import UUID

from .models import TaskStatus


class TaskDomainError(Exception):
    """Base class for every Task Memory Service domain error."""


class FeatureNotFoundError(TaskDomainError):
    """The feature a task/task-graph operation targets doesn't exist. Distinct from
    `aep.modules.projects.domain.errors.FeatureNotFoundError` — Task Memory's `services/` layer
    catches that one (the exception contract of the Project Service's public `FeatureService`
    it calls into) and re-raises this one, so this module's own `api/` layer only ever has to
    translate its own domain errors, never a collaborator module's."""

    def __init__(self, feature_id: UUID) -> None:
        super().__init__(f"feature {feature_id} not found")
        self.feature_id = feature_id


class TaskNotFoundError(TaskDomainError):
    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"task {task_id} not found")
        self.task_id = task_id


class TaskDependencyNotFoundError(TaskDomainError):
    def __init__(self, dependency_id: UUID) -> None:
        super().__init__(f"task dependency {dependency_id} not found")
        self.dependency_id = dependency_id


class IllegalTaskStatusTransitionError(TaskDomainError):
    def __init__(self, current: TaskStatus, target: TaskStatus) -> None:
        super().__init__(f"cannot transition task from {current.value!r} to {target.value!r}")
        self.current = current
        self.target = target


class UnmetDependenciesError(TaskDomainError):
    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"task {task_id} has dependencies that are not yet merged")
        self.task_id = task_id


class SelfDependencyError(TaskDomainError):
    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"task {task_id} cannot depend on itself")
        self.task_id = task_id


class DuplicateDependencyError(TaskDomainError):
    def __init__(self, task_id: UUID, depends_on_task_id: UUID) -> None:
        super().__init__(f"task {task_id} already depends on {depends_on_task_id}")
        self.task_id = task_id
        self.depends_on_task_id = depends_on_task_id


class CyclicDependencyError(TaskDomainError):
    def __init__(self, task_id: UUID, depends_on_task_id: UUID) -> None:
        super().__init__(
            f"adding a dependency from {task_id} on {depends_on_task_id} would create a cycle"
        )
        self.task_id = task_id
        self.depends_on_task_id = depends_on_task_id
