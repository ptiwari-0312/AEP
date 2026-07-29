"""Recording and querying the audit trail (docs/architecture/03-db-design.md §17;
docs/architecture/04-api-design.md §10).

Only this module's own login/logout flow calls `record_event()` in this pass, to prove the write
path end-to-end — wiring every other module's mutating endpoints to actually call it is a
deliberately separate follow-up (see `modules/auth/README.md`), not attempted here as a retrofit
across already-built modules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from ..domain.models import AuditEvent
from ..repository.audit_event_repository import AuditEventRepository


class AuditService:
    def __init__(self, audit_event_repository: AuditEventRepository) -> None:
        self._events = audit_event_repository

    async def record_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: UUID,
        actor_user_id: UUID | None = None,
        actor_agent_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        if actor_user_id is None and actor_agent_id is None:
            raise ValueError("record_event requires actor_user_id or actor_agent_id")
        return await self._events.add(
            AuditEvent(
                id=uuid4(),
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_agent_id=actor_agent_id,
                payload=payload or {},
            )
        )

    async def list_events(
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
        return await self._events.list(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_agent_id=actor_agent_id,
            created_at_from=created_at_from,
            created_at_to=created_at_to,
            cursor=cursor,
            limit=limit,
        )

    async def get_event(self, event_id: UUID) -> AuditEvent | None:
        return await self._events.get_by_id(event_id)
