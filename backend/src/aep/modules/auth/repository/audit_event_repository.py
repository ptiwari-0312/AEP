"""Data access for `audit_events` (docs/architecture/03-db-design.md §17) — append-only,
cursor-paginated newest-first, matching `GET /audit-events`
(docs/architecture/04-api-design.md §10). This repository only ever inserts and selects — never
updates or deletes a row, mirroring the "app DB role has INSERT only" operational rule the DB
design doc calls for at the database-permission level.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.pagination import decode_cursor, encode_cursor

from ..domain.models import AuditEvent
from .models import AuditEventModel


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: AuditEvent) -> AuditEvent:
        model = AuditEventModel(
            id=event.id,
            actor_user_id=event.actor_user_id,
            actor_agent_id=event.actor_agent_id,
            event_type=event.event_type,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            payload=event.payload,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, event_id: UUID) -> AuditEvent | None:
        model = await self._session.get(AuditEventModel, event_id)
        return _to_domain(model) if model else None

    async def list(
        self,
        *,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        event_type: str | None = None,
        actor_user_id: UUID | None = None,
        actor_agent_id: UUID | None = None,
        created_at_from: datetime | None = None,
        created_at_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[AuditEvent], str | None, bool]:
        query = select(AuditEventModel)
        if entity_type is not None:
            query = query.where(AuditEventModel.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditEventModel.entity_id == entity_id)
        if event_type is not None:
            query = query.where(AuditEventModel.event_type == event_type)
        if actor_user_id is not None:
            query = query.where(AuditEventModel.actor_user_id == actor_user_id)
        if actor_agent_id is not None:
            query = query.where(AuditEventModel.actor_agent_id == actor_agent_id)
        if created_at_from is not None:
            query = query.where(AuditEventModel.created_at >= created_at_from)
        if created_at_to is not None:
            query = query.where(AuditEventModel.created_at <= created_at_to)
        if cursor is not None:
            cursor_created_at, cursor_id = decode_cursor(cursor)
            query = query.where(
                or_(
                    AuditEventModel.created_at < cursor_created_at,
                    and_(
                        AuditEventModel.created_at == cursor_created_at,
                        AuditEventModel.id < cursor_id,
                    ),
                )
            )
        query = query.order_by(AuditEventModel.created_at.desc(), AuditEventModel.id.desc())
        query = query.limit(limit + 1)

        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        return [_to_domain(m) for m in rows], next_cursor, has_more


def _to_domain(model: AuditEventModel) -> AuditEvent:
    return AuditEvent(
        id=model.id,
        event_type=model.event_type,
        entity_type=model.entity_type,
        entity_id=model.entity_id,
        actor_user_id=model.actor_user_id,
        actor_agent_id=model.actor_agent_id,
        payload=model.payload,
        created_at=model.created_at,
    )
