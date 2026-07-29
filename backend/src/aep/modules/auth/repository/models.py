"""SQLAlchemy ORM models for the Authentication Service's tables
(docs/architecture/03-db-design.md §1-2, §16 [`refresh_tokens`], §17). Lives here, not in
`domain/` (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from aep.core.db import Base, utcnow

# Native JSONB on Postgres; falls back to SQLAlchemy's generic JSON (TEXT-serialized) elsewhere
# — e.g. SQLite in tests. DB design §17 specifies JSONB for the real deployment target.
_JSONVariant = JSON().with_variant(JSONB, "postgresql")


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    auth_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("auth_provider", "auth_subject", name="uq_users_provider_subject"),
        CheckConstraint("status IN ('active','disabled')", name="ck_users_status"),
    )


class RoleModel(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UserRoleModel(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("roles.id", ondelete="CASCADE"))
    granted_at: Mapped[datetime] = mapped_column(default=utcnow)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (PrimaryKeyConstraint("user_id", "role_id"),)


class RefreshTokenModel(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # No FK to agents.id yet — the (not-yet-built) Agent Orchestrator module owns that table.
    actor_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Intentionally no FK — polymorphic reference across every module's tables, including ones
    # added later, per docs/architecture/03-db-design.md §17's one deliberate exception to
    # "every relationship has a FK."
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONVariant, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "actor_user_id IS NOT NULL OR actor_agent_id IS NOT NULL",
            name="ck_audit_events_actor_present",
        ),
    )
