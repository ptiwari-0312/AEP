"""SQLAlchemy ORM models for the Project Service's tables
(docs/architecture/03-db-design.md §3-5). Lives here, not in `domain/`, so `domain/` stays
framework-free (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from aep.core.db import Base


class GitRepositoryModel(Base):
    __tablename__ = "git_repositories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False, default="main")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "provider IN ('github','gitlab','bitbucket','other')",
            name="ck_git_repositories_provider",
        ),
    )


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_repository_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("git_repositories.id", ondelete="SET NULL"), nullable=True
    )
    # No FK to `users.id` yet — the auth module, which owns that table
    # (docs/architecture/02-repo-design.md §2), doesn't exist in this repo yet. Add
    # ForeignKey("users.id", ondelete="RESTRICT") once it does (docs/architecture/03-db-design.md §4).
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    features: Mapped[list[FeatureModel]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (CheckConstraint("status IN ('active','archived')", name="ck_projects_status"),)


class FeatureModel(Base):
    __tablename__ = "features"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # created_by: same FK gap as ProjectModel.owner_user_id above.
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    project: Mapped[ProjectModel] = relationship(back_populates="features")

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','in_progress','in_review','done','cancelled')",
            name="ck_features_status",
        ),
    )
