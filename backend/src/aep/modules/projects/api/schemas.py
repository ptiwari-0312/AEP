"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §2 exactly —
no DB or provider calls in this layer (docs/architecture/02-repo-design.md §2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import FeatureStatus, ProjectStatus


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=10_000)
    git_repository_id: UUID | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)


class AttachRepositoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=1, max_length=500)
    provider: Literal["github", "gitlab", "bitbucket", "other"]
    default_branch: str = Field(default="main", max_length=255)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    description: str | None
    git_repository_id: UUID | None
    owner_user_id: UUID
    status: ProjectStatus
    created_at: datetime | None
    updated_at: datetime | None


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    page: int
    page_size: int
    total: int


class FeatureCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)


class FeatureUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)


class FeatureStatusTransitionRequest(BaseModel):
    to_status: FeatureStatus
    reason: str | None = None


class FeatureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    description: str | None
    status: FeatureStatus
    created_by: UUID
    created_at: datetime | None
    updated_at: datetime | None
