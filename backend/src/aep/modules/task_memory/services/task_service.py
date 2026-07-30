"""Use-case orchestration for Tasks (docs/architecture/02-repo-design.md §2's `services/`
layer): the task status state machine, the dependency-satisfaction gate, cycle detection for
the dependency graph, and execution-history recording all live here — none of it in the
repository or API layers.

Checking that a Feature exists means calling into the Project Service module's public
`services/` interface (`ProjectsFeatureService`), per the "cross-module calls go through the
other module's services/ public interface" rule (docs/architecture/02-repo-design.md §2) — never
`aep.modules.projects.repository` directly. The one exception is
`aep.modules.projects.domain.errors.FeatureNotFoundError`: that exception type is part of
`ProjectsFeatureService.get_feature()`'s public contract (the thing it documents itself as
raising), not an internal detail, so catching it here to translate into this module's own
`FeatureNotFoundError` is the intended boundary — not a domain-layer violation.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from aep.modules.projects.domain.errors import (
    FeatureNotFoundError as ProjectsFeatureNotFoundError,
)
from aep.modules.projects.services import FeatureService as ProjectsFeatureService

from ..domain.errors import (
    CyclicDependencyError,
    DuplicateDependencyError,
    FeatureNotFoundError,
    IllegalTaskStatusTransitionError,
    SelfDependencyError,
    TaskDependencyNotFoundError,
    TaskNotFoundError,
    UnmetDependenciesError,
)
from ..domain.models import (
    DependencyType,
    ExecutionHistoryEntry,
    Task,
    TaskDependency,
    TaskStatus,
    TaskType,
    is_legal_task_transition,
    requires_dependencies_satisfied,
)
from ..repository.execution_history_repository import ExecutionHistoryRepository
from ..repository.task_dependency_repository import TaskDependencyRepository
from ..repository.task_repository import TaskRepository


class TaskService:
    def __init__(
        self,
        task_repository: TaskRepository,
        dependency_repository: TaskDependencyRepository,
        history_repository: ExecutionHistoryRepository,
        projects_feature_service: ProjectsFeatureService,
    ) -> None:
        self._tasks = task_repository
        self._dependencies = dependency_repository
        self._history = history_repository
        self._features = projects_feature_service

    async def _ensure_feature_exists(self, feature_id: UUID) -> None:
        try:
            await self._features.get_feature(feature_id)
        except ProjectsFeatureNotFoundError as exc:
            raise FeatureNotFoundError(feature_id) from exc

    async def create_task(
        self,
        *,
        feature_id: UUID,
        title: str,
        task_type: TaskType,
        description: str | None = None,
        priority: int = 0,
    ) -> Task:
        await self._ensure_feature_exists(feature_id)
        task = Task(
            id=uuid4(),
            feature_id=feature_id,
            title=title,
            task_type=task_type,
            description=description,
            priority=priority,
        )
        return await self._tasks.add(task)

    async def get_task(self, task_id: UUID) -> Task:
        task = await self._tasks.get_by_id(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def list_tasks_for_feature(
        self,
        feature_id: UUID,
        *,
        status: TaskStatus | None = None,
        task_type: TaskType | None = None,
        assigned_agent_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Task], str | None, bool]:
        await self._ensure_feature_exists(feature_id)
        return await self._tasks.list_for_feature(
            feature_id,
            status=status,
            task_type=task_type,
            assigned_agent_id=assigned_agent_id,
            cursor=cursor,
            limit=limit,
        )

    async def update_task(
        self,
        task_id: UUID,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
    ) -> Task:
        task = await self.get_task(task_id)
        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if priority is not None:
            task.priority = priority
        return await self._tasks.update(task)

    async def assign_agent(self, task_id: UUID, *, agent_id: UUID | None) -> Task:
        """Sets/clears `assigned_agent_id` — a separate method from `update_task()` rather than
        folding it in there, since assignment is the Agent Orchestrator module's concern
        (docs/architecture/04-api-design.md §5's `POST /tasks/{taskId}/assign`), not this
        module's own `PATCH /tasks/{taskId}` contract. Confirming `agent_id` refers to a real,
        enabled agent is the *caller's* job (this module has no visibility into the `agents`
        table, owned by `orchestrator`) — this method only persists the reference."""
        task = await self.get_task(task_id)
        task.assigned_agent_id = agent_id
        return await self._tasks.update(task)

    async def list_dependencies(self, task_id: UUID) -> list[TaskDependency]:
        """Edges where `task_id` is the dependent — what it depends on. Backs the `depends_on`
        field on `TaskResponse` (docs/architecture/04-api-design.md §3)."""
        return await self._dependencies.list_for_task(task_id)

    async def add_dependency(
        self,
        task_id: UUID,
        *,
        depends_on_task_id: UUID,
        dependency_type: DependencyType = DependencyType.BLOCKS,
    ) -> TaskDependency:
        if task_id == depends_on_task_id:
            raise SelfDependencyError(task_id)
        await self.get_task(task_id)
        await self.get_task(depends_on_task_id)
        if await self._dependencies.exists(task_id, depends_on_task_id):
            raise DuplicateDependencyError(task_id, depends_on_task_id)
        if await self._would_create_cycle(task_id, depends_on_task_id):
            raise CyclicDependencyError(task_id, depends_on_task_id)
        dependency = TaskDependency(
            id=uuid4(),
            task_id=task_id,
            depends_on_task_id=depends_on_task_id,
            dependency_type=dependency_type,
        )
        return await self._dependencies.add(dependency)

    async def _would_create_cycle(self, task_id: UUID, depends_on_task_id: UUID) -> bool:
        """BFS forward through the "depends on" chain starting at `depends_on_task_id`; if it
        ever reaches `task_id`, adding `task_id -> depends_on_task_id` would close a cycle."""
        visited: set[UUID] = set()
        frontier = [depends_on_task_id]
        while frontier:
            current = frontier.pop()
            if current == task_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            for dependency in await self._dependencies.list_for_task(current):
                frontier.append(dependency.depends_on_task_id)
        return False

    async def remove_dependency(self, dependency_id: UUID) -> None:
        dependency = await self._dependencies.get_by_id(dependency_id)
        if dependency is None:
            raise TaskDependencyNotFoundError(dependency_id)
        await self._dependencies.delete(dependency_id)

    async def transition_status(
        self,
        task_id: UUID,
        *,
        to_status: TaskStatus,
        reason: str | None = None,
        changed_by_user_id: UUID | None = None,
        changed_by_agent_id: UUID | None = None,
    ) -> Task:
        if changed_by_user_id is None and changed_by_agent_id is None:
            raise ValueError(
                "transition_status requires changed_by_user_id or changed_by_agent_id"
            )
        task = await self.get_task(task_id)
        if not is_legal_task_transition(task.status, to_status):
            raise IllegalTaskStatusTransitionError(task.status, to_status)
        if requires_dependencies_satisfied(to_status) and not await self._dependencies_satisfied(
            task_id
        ):
            raise UnmetDependenciesError(task_id)

        from_status = task.status
        task.status = to_status
        updated = await self._tasks.update(task)
        await self._history.add(
            ExecutionHistoryEntry(
                id=uuid4(),
                task_id=task_id,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                changed_by_user_id=changed_by_user_id,
                changed_by_agent_id=changed_by_agent_id,
            )
        )
        return updated

    async def _dependencies_satisfied(self, task_id: UUID) -> bool:
        for dependency in await self._dependencies.list_for_task(task_id):
            if dependency.dependency_type != DependencyType.BLOCKS:
                continue
            depended_on = await self._tasks.get_by_id(dependency.depends_on_task_id)
            if depended_on is None or depended_on.status != TaskStatus.MERGED:
                return False
        return True

    async def list_execution_history(
        self, task_id: UUID, *, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[ExecutionHistoryEntry], str | None, bool]:
        await self.get_task(task_id)
        return await self._history.list_for_task(task_id, cursor=cursor, limit=limit)
