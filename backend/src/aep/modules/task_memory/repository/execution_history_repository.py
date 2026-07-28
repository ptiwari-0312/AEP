"""Data access for `execution_history` (docs/architecture/03-db-design.md §19) — append-only,
newest-first (matching the Dashboard's timeline view use case,
docs/architecture/08-dashboard-ux.md §6)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import ExecutionHistoryEntry, TaskStatus
from .cursor import decode_cursor, encode_cursor
from .models import ExecutionHistoryModel


class ExecutionHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: ExecutionHistoryEntry) -> ExecutionHistoryEntry:
        model = ExecutionHistoryModel(
            id=entry.id,
            task_id=entry.task_id,
            from_status=entry.from_status.value if entry.from_status else None,
            to_status=entry.to_status.value,
            changed_by_user_id=entry.changed_by_user_id,
            changed_by_agent_id=entry.changed_by_agent_id,
            reason=entry.reason,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def list_for_task(
        self, task_id: UUID, *, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[ExecutionHistoryEntry], str | None, bool]:
        query = select(ExecutionHistoryModel).where(ExecutionHistoryModel.task_id == task_id)
        if cursor is not None:
            cursor_created_at, cursor_id = decode_cursor(cursor)
            query = query.where(
                or_(
                    ExecutionHistoryModel.created_at < cursor_created_at,
                    and_(
                        ExecutionHistoryModel.created_at == cursor_created_at,
                        ExecutionHistoryModel.id < cursor_id,
                    ),
                )
            )
        query = query.order_by(
            ExecutionHistoryModel.created_at.desc(), ExecutionHistoryModel.id.desc()
        ).limit(limit + 1)

        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        return [_to_domain(m) for m in rows], next_cursor, has_more


def _to_domain(model: ExecutionHistoryModel) -> ExecutionHistoryEntry:
    return ExecutionHistoryEntry(
        id=model.id,
        task_id=model.task_id,
        to_status=TaskStatus(model.to_status),
        from_status=TaskStatus(model.from_status) if model.from_status else None,
        changed_by_user_id=model.changed_by_user_id,
        changed_by_agent_id=model.changed_by_agent_id,
        reason=model.reason,
        created_at=model.created_at,
    )
