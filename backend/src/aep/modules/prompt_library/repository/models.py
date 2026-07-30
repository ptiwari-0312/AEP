"""SQLAlchemy ORM models for the Prompt Library's tables (docs/architecture/03-db-design.md
§10-11). Lives here, not in `domain/`, so `domain/` stays framework-free
(docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from aep.core.db import Base, utcnow

_ACTIVE_CONDITION = text("is_active")


class PromptTemplateModel(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # No FK to `users.id`: same cross-module `create_all()` ripple reason as every other
    # module's deferred FKs (see `modules/projects/repository/models.py`'s note on
    # `owner_user_id`) — `users` is owned by `auth`.
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class PromptVersionModel(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Real FK: `prompt_templates` is owned by this same module.
    prompt_template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("prompt_templates.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # No FK to `users.id`, same reason as `PromptTemplateModel.owner_user_id` above.
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        Index(
            "ix_prompt_versions_template_version_number",
            "prompt_template_id",
            "version_number",
            unique=True,
        ),
        # The DB design's actual enforcement mechanism (docs/architecture/09-engineering-
        # standards.md §9: "Enforced by: the DB's partial-unique-active-version constraint") —
        # at most one active version per template, at the database level, not just in
        # application code. `sqlite_where`/`postgresql_where` give a real partial index on both
        # backends this project actually runs against (SQLite in tests, Postgres in
        # production), not a decorative comment — proven by a test that bypasses the service
        # layer's own deactivate-then-activate ordering and expects the DB to reject it anyway.
        Index(
            "ix_prompt_versions_one_active_per_template",
            "prompt_template_id",
            unique=True,
            sqlite_where=_ACTIVE_CONDITION,
            postgresql_where=_ACTIVE_CONDITION,
        ),
    )
