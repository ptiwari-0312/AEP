"""Data access for `tasks` (docs/architecture/03-db-design.md §6)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Task, TaskStatus, TaskType
from .cursor import decode_cursor, encode_cursor
from .models import TaskModel


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, task: Task) -> Task:
        model = _to_model(task)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, task_id: UUID) -> Task | None:
        model = await self._session.get(TaskModel, task_id)
        return _to_domain(model) if model else None

    async def list_for_feature(
        self,
        feature_id: UUID,
        *,
        status: TaskStatus | None = None,
        task_type: TaskType | None = None,
        assigned_agent_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Task], str | None, bool]:
        query = select(TaskModel).where(TaskModel.feature_id == feature_id)
        if status is not None:
            query = query.where(TaskModel.status == status.value)
        if task_type is not None:
            query = query.where(TaskModel.task_type == task_type.value)
        if assigned_agent_id is not None:
            query = query.where(TaskModel.assigned_agent_id == assigned_agent_id)
        if cursor is not None:
            cursor_created_at, cursor_id = decode_cursor(cursor)
            query = query.where(
                or_(
                    TaskModel.created_at > cursor_created_at,
                    and_(TaskModel.created_at == cursor_created_at, TaskModel.id > cursor_id),
                )
            )
        query = query.order_by(TaskModel.created_at.asc(), TaskModel.id.asc()).limit(limit + 1)

        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        return [_to_domain(m) for m in rows], next_cursor, has_more

    async def update(self, task: Task) -> Task:
        model = await self._session.get(TaskModel, task.id)
        if model is None:
            raise ValueError(f"task {task.id} does not exist — call add() first")
        model.title = task.title
        model.description = task.description
        model.status = task.status.value
        model.assigned_agent_id = task.assigned_agent_id
        model.priority = task.priority
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)


def _to_domain(model: TaskModel) -> Task:
    return Task(
        id=model.id,
        feature_id=model.feature_id,
        title=model.title,
        task_type=TaskType(model.task_type),
        description=model.description,
        status=TaskStatus(model.status),
        assigned_agent_id=model.assigned_agent_id,
        priority=model.priority,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_model(task: Task) -> TaskModel:
    return TaskModel(
        id=task.id,
        feature_id=task.feature_id,
        title=task.title,
        task_type=task.task_type.value,
        description=task.description,
        status=task.status.value,
        assigned_agent_id=task.assigned_agent_id,
        priority=task.priority,
    )
