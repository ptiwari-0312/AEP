"""Pure domain entities and value objects for the Authentication Service
(docs/architecture/03-db-design.md §1-2, §16 [`refresh_tokens`], §17;
docs/architecture/02-repo-design.md §2's domain/ layer — zero framework imports).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass
class User:
    id: UUID
    email: str
    display_name: str
    auth_provider: str
    auth_subject: str
    status: UserStatus = UserStatus.ACTIVE
    # Resolved by the service layer (a join through user_roles), not stored on this table —
    # mirrors GET /users/me's response shape (docs/architecture/04-api-design.md §1).
    roles: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Role:
    id: UUID
    name: str
    description: str | None = None
    created_at: datetime | None = None


@dataclass
class UserRole:
    user_id: UUID
    role_id: UUID
    granted_at: datetime | None = None
    granted_by: UUID | None = None


@dataclass
class RefreshToken:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class AuditEvent:
    id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID
    actor_user_id: UUID | None = None
    actor_agent_id: UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
