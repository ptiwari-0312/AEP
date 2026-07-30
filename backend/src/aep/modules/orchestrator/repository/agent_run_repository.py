"""Data access for `agent_runs` (docs/architecture/03-db-design.md §9). Cursor-paginated per
docs/architecture/04-api-design.md §0.3, which names "agent runs" explicitly as one of the
high-volume/append-only collections — unlike `agents`, which is offset-paginated.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.pagination import decode_cursor, encode_cursor

from ..domain.models import AgentRun, AgentRunStatus
from .models import AgentRunModel


class AgentRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, agent_run: AgentRun) -> AgentRun:
        model = _to_model(agent_run)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, agent_run_id: UUID) -> AgentRun | None:
        model = await self._session.get(AgentRunModel, agent_run_id)
        return _to_domain(model) if model else None

    async def list_for_task(
        self, task_id: UUID, *, cursor: str | None = None, limit: int = 50
    ) -> tuple[list[AgentRun], str | None, bool]:
        query = select(AgentRunModel).where(AgentRunModel.task_id == task_id)
        if cursor is not None:
            cursor_created_at, cursor_id = decode_cursor(cursor)
            query = query.where(
                or_(
                    AgentRunModel.created_at > cursor_created_at,
                    and_(
                        AgentRunModel.created_at == cursor_created_at,
                        AgentRunModel.id > cursor_id,
                    ),
                )
            )
        query = query.order_by(AgentRunModel.created_at.asc(), AgentRunModel.id.asc()).limit(
            limit + 1
        )

        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        return [_to_domain(m) for m in rows], next_cursor, has_more

    async def get_latest_for_task(self, task_id: UUID) -> AgentRun | None:
        """The task's most recently created run — what `GET /tasks/{taskId}/quality-gate`
        (docs/architecture/04-api-design.md §7) aggregates evaluations against. Added while
        building the `evaluation` module; `list_for_task()`'s ascending cursor order isn't a
        convenient way to get "the latest one" for a caller that doesn't want pagination."""
        query = (
            select(AgentRunModel)
            .where(AgentRunModel.task_id == task_id)
            .order_by(AgentRunModel.created_at.desc(), AgentRunModel.id.desc())
            .limit(1)
        )
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def update(self, agent_run: AgentRun) -> AgentRun:
        model = await self._session.get(AgentRunModel, agent_run.id)
        if model is None:
            raise ValueError(f"agent run {agent_run.id} does not exist — call add() first")
        model.status = agent_run.status.value
        model.attempt_number = agent_run.attempt_number
        model.started_at = agent_run.started_at
        model.completed_at = agent_run.completed_at
        model.input_tokens = agent_run.input_tokens
        model.output_tokens = agent_run.output_tokens
        model.cost_usd = agent_run.cost_usd
        model.error_message = agent_run.error_message
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)


def _to_domain(model: AgentRunModel) -> AgentRun:
    return AgentRun(
        id=model.id,
        agent_id=model.agent_id,
        task_id=model.task_id,
        context_package_id=model.context_package_id,
        provider=model.provider,
        model_name=model.model_name,
        status=AgentRunStatus(model.status),
        attempt_number=model.attempt_number,
        started_at=model.started_at,
        completed_at=model.completed_at,
        input_tokens=model.input_tokens,
        output_tokens=model.output_tokens,
        cost_usd=model.cost_usd,
        error_message=model.error_message,
        created_at=model.created_at,
    )


def _to_model(agent_run: AgentRun) -> AgentRunModel:
    return AgentRunModel(
        id=agent_run.id,
        agent_id=agent_run.agent_id,
        task_id=agent_run.task_id,
        context_package_id=agent_run.context_package_id,
        provider=agent_run.provider,
        model_name=agent_run.model_name,
        status=agent_run.status.value,
        attempt_number=agent_run.attempt_number,
        started_at=agent_run.started_at,
        completed_at=agent_run.completed_at,
        input_tokens=agent_run.input_tokens,
        output_tokens=agent_run.output_tokens,
        cost_usd=agent_run.cost_usd,
        error_message=agent_run.error_message,
    )
