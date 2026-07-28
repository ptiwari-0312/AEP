"""Data access for `task_dependencies` (docs/architecture/03-db-design.md §7). Cycle-freedom
is enforced by the service layer (a graph invariant, not a single-row SQL constraint, per the
DB design doc) — this repository only stores/queries edges.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import DependencyType, TaskDependency
from .models import TaskDependencyModel


class TaskDependencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, dependency: TaskDependency) -> TaskDependency:
        model = TaskDependencyModel(
            id=dependency.id,
            task_id=dependency.task_id,
            depends_on_task_id=dependency.depends_on_task_id,
            dependency_type=dependency.dependency_type.value,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, dependency_id: UUID) -> TaskDependency | None:
        model = await self._session.get(TaskDependencyModel, dependency_id)
        return _to_domain(model) if model else None

    async def list_for_task(self, task_id: UUID) -> list[TaskDependency]:
        """Edges where `task_id` is the dependent — i.e., what it depends on."""
        result = await self._session.execute(
            select(TaskDependencyModel).where(TaskDependencyModel.task_id == task_id)
        )
        return [_to_domain(m) for m in result.scalars().all()]

    async def exists(self, task_id: UUID, depends_on_task_id: UUID) -> bool:
        result = await self._session.execute(
            select(TaskDependencyModel.id).where(
                TaskDependencyModel.task_id == task_id,
                TaskDependencyModel.depends_on_task_id == depends_on_task_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def delete(self, dependency_id: UUID) -> None:
        model = await self._session.get(TaskDependencyModel, dependency_id)
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()


def _to_domain(model: TaskDependencyModel) -> TaskDependency:
    return TaskDependency(
        id=model.id,
        task_id=model.task_id,
        depends_on_task_id=model.depends_on_task_id,
        dependency_type=DependencyType(model.dependency_type),
        created_at=model.created_at,
    )
