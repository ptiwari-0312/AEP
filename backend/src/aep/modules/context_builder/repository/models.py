"""SQLAlchemy ORM models for the Context Builder's tables
(docs/architecture/03-db-design.md §12-13, §16). Lives here, not in `domain/`, so `domain/`
stays framework-free (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from aep.core.db import Base, utcnow

_DOC_TYPE_CHECK = (
    "doc_type IN ('source_file','architecture_doc','coding_standard','api_spec',"
    "'pull_request','dependency_graph','evaluation_history','prompt_template')"
)


class SourceDocumentModel(Base):
    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # No FK to `projects.id`: same cross-module `create_all()` ripple reason as
    # `ProjectModel.owner_user_id` (see that module's repository/models.py) — deferred to a real
    # Alembic migration rather than forcing every test here to import the `projects` module too.
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_indexed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint(_DOC_TYPE_CHECK, name="ck_source_documents_doc_type"),
        Index("ix_source_documents_project_uri", "project_id", "uri", unique=True),
        Index("ix_source_documents_project_doc_type", "project_id", "doc_type"),
    )


class ContextPackageModel(Base):
    __tablename__ = "context_packages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # No FK to `tasks.id`: same cross-module deferral as above — `tasks` is owned by the
    # `task_memory` module.
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ranking_algorithm_version: Mapped[str] = mapped_column(String(50), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(default=utcnow)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint("token_count >= 0", name="ck_context_packages_token_count"),
        Index("ix_context_packages_task_id", "task_id"),
    )


class ContextPackageSourceModel(Base):
    __tablename__ = "context_package_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Both context_packages and source_documents are owned by *this* module, so unlike
    # project_id/task_id above, these two FKs are real — no cross-module create_all() ripple.
    context_package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("context_packages.id", ondelete="CASCADE"), nullable=False
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=False
    )
    # asdecimal=False: the domain model uses `float`, and this score only ever feeds ranking
    # comparisons/JSON responses — Decimal's extra precision buys nothing here.
    relevance_score: Mapped[float] = mapped_column(
        Numeric(6, 4, asdecimal=False), nullable=False
    )
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        Index(
            "ix_context_package_sources_package_document",
            "context_package_id",
            "source_document_id",
            unique=True,
        ),
        Index("ix_context_package_sources_package_rank", "context_package_id", "rank"),
    )
