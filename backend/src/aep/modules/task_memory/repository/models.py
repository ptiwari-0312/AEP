"""SQLAlchemy ORM models for the Task Memory Service's tables
(docs/architecture/03-db-design.md §6-7, §19). Lives here, not in `domain/`
(docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from aep.core.db import Base, utcnow

_TASK_STATUS_VALUES = (
    "pending",
    "ready",
    "running",
    "blocked",
    "evaluating",
    "awaiting_approval",
    "approved",
    "rejected",
    "merged",
    "failed",
    "cancelled",
)
_TASK_TYPE_VALUES = ("plan", "architect", "code", "test", "review", "document", "security", "evaluate")


def _sql_in_clause(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # No FK to `features.id` yet — `features` lives in the projects module's own table, and
    # cross-module FKs are a schema-ownership question deferred until both modules' Alembic
    # migrations are actually generated together against one real database (neither exists yet).
    feature_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # No FK to `agents.id` yet — the (not-yet-built) Agent Orchestrator module owns that table.
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(_sql_in_clause("status", _TASK_STATUS_VALUES), name="ck_tasks_status"),
        CheckConstraint(_sql_in_clause("task_type", _TASK_TYPE_VALUES), name="ck_tasks_task_type"),
        Index("ix_tasks_feature_id_status", "feature_id", "status"),
        Index("ix_tasks_assigned_agent_id", "assigned_agent_id"),
        Index("ix_tasks_status_priority", "status", "priority"),
    )


class TaskDependencyModel(Base):
    __tablename__ = "task_dependencies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    dependency_type: Mapped[str] = mapped_column(String(20), nullable=False, default="blocks")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependencies_edge"),
        CheckConstraint("task_id != depends_on_task_id", name="ck_task_dependencies_no_self_edge"),
        CheckConstraint(
            "dependency_type IN ('blocks','informs')", name="ck_task_dependencies_type"
        ),
        Index("ix_task_dependencies_depends_on_task_id", "depends_on_task_id"),
    )


class ExecutionHistoryModel(Base):
    __tablename__ = "execution_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    # changed_by_agent_id: no FK yet, same gap as TaskModel.assigned_agent_id above (agents
    # table doesn't exist). changed_by_user_id: the users table exists now, but see
    # ProjectModel.owner_user_id's comment in modules/projects/repository/models.py for why the
    # FK is still deferred (a real Alembic migration, not a mechanical test-fixture-import
    # ripple, is the right place to add it).
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    changed_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint(
            "changed_by_user_id IS NOT NULL OR changed_by_agent_id IS NOT NULL",
            name="ck_execution_history_actor_present",
        ),
        Index("ix_execution_history_task_id_created_at", "task_id", "created_at"),
    )
