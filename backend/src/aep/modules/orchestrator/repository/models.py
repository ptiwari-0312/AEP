"""SQLAlchemy ORM models for the Agent Orchestrator's tables
(docs/architecture/03-db-design.md §8-9). Lives here, not in `domain/`, so `domain/` stays
framework-free (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aep.core.db import Base, utcnow

_AGENT_TYPE_CHECK = (
    "agent_type IN ('planner','architect','coding','testing','review','documentation',"
    "'security','evaluation')"
)
_STATUS_CHECK = "status IN ('queued','running','succeeded','failed','cancelled','retrying')"


class AgentModel(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    # Generic JSON, JSONB on Postgres via .with_variant() — same pattern as
    # `auth.repository.models.AuditEventModel.payload`.
    config: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(_AGENT_TYPE_CHECK, name="ck_agents_agent_type"),
        Index("ix_agents_name_version", "name", "version", unique=True),
        # DB design's partial index (`WHERE is_enabled`) is a query-performance optimization,
        # not a correctness constraint — modeled here as a plain composite index for
        # cross-backend portability rather than dialect-specific partial-index syntax.
        Index("ix_agents_agent_type_is_enabled", "agent_type", "is_enabled"),
    )


class AgentRunModel(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Real FK: `agents` is owned by this same module.
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    # No FK to `tasks.id`/`context_packages.id`: same cross-module `create_all()` ripple reason
    # as every other module's deferred FKs (see `modules/projects/repository/models.py`'s note
    # on `owner_user_id`) — `tasks` is owned by `task_memory`, `context_packages` by
    # `context_builder`.
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    context_package_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6, asdecimal=False), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_agent_runs_status"),
        CheckConstraint("attempt_number >= 1", name="ck_agent_runs_attempt_number"),
        CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="ck_agent_runs_completed_after_started",
        ),
        Index("ix_agent_runs_task_id_status", "task_id", "status"),
        Index("ix_agent_runs_agent_id", "agent_id"),
        Index("ix_agent_runs_created_at", "created_at"),
    )
