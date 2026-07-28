"""Pure domain entities and value objects for the Project Service
(docs/architecture/03-db-design.md §3-5; docs/architecture/02-repo-design.md §2's domain/ layer
— zero framework imports, so this stays unit-testable with no fixtures).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class FeatureStatus(str, Enum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


# Legal transitions per docs/architecture/04-api-design.md §2 (`POST /features/{id}/status`).
# DONE and CANCELLED are terminal — no edge leaves either.
_FEATURE_TRANSITIONS: dict[FeatureStatus, frozenset[FeatureStatus]] = {
    FeatureStatus.DRAFT: frozenset({FeatureStatus.IN_PROGRESS, FeatureStatus.CANCELLED}),
    FeatureStatus.IN_PROGRESS: frozenset({FeatureStatus.IN_REVIEW, FeatureStatus.CANCELLED}),
    FeatureStatus.IN_REVIEW: frozenset(
        {FeatureStatus.DONE, FeatureStatus.IN_PROGRESS, FeatureStatus.CANCELLED}
    ),
    FeatureStatus.DONE: frozenset(),
    FeatureStatus.CANCELLED: frozenset(),
}


def is_legal_feature_transition(current: FeatureStatus, target: FeatureStatus) -> bool:
    return target in _FEATURE_TRANSITIONS[current]


@dataclass
class GitRepository:
    id: UUID
    name: str
    url: str
    provider: str
    default_branch: str = "main"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Project:
    id: UUID
    name: str
    slug: str
    owner_user_id: UUID
    description: str | None = None
    git_repository_id: UUID | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Feature:
    id: UUID
    project_id: UUID
    title: str
    created_by: UUID
    description: str | None = None
    status: FeatureStatus = FeatureStatus.DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None
