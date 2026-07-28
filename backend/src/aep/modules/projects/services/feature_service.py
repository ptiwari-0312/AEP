"""Use-case orchestration for Features (docs/architecture/02-repo-design.md §2's `services/`
layer) — the feature status state machine (docs/architecture/04-api-design.md §2's
`POST /features/{id}/status`) is enforced here, not in the repository or the API layer.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from ..domain.errors import (
    FeatureNotFoundError,
    IllegalFeatureStatusTransitionError,
    ProjectNotFoundError,
)
from ..domain.models import Feature, FeatureStatus, is_legal_feature_transition
from ..repository.feature_repository import FeatureRepository
from ..repository.project_repository import ProjectRepository


class FeatureService:
    def __init__(self, feature_repository: FeatureRepository, project_repository: ProjectRepository) -> None:
        self._features = feature_repository
        self._projects = project_repository

    async def create_feature(
        self, *, project_id: UUID, title: str, created_by: UUID, description: str | None = None
    ) -> Feature:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        feature = Feature(
            id=uuid4(), project_id=project_id, title=title, description=description, created_by=created_by
        )
        return await self._features.add(feature)

    async def get_feature(self, feature_id: UUID) -> Feature:
        feature = await self._features.get_by_id(feature_id)
        if feature is None:
            raise FeatureNotFoundError(feature_id)
        return feature

    async def list_features_for_project(
        self, project_id: UUID, *, status: FeatureStatus | None = None
    ) -> list[Feature]:
        if await self._projects.get_by_id(project_id) is None:
            raise ProjectNotFoundError(project_id)
        return await self._features.list_for_project(project_id, status=status)

    async def update_feature(
        self, feature_id: UUID, *, title: str | None = None, description: str | None = None
    ) -> Feature:
        feature = await self.get_feature(feature_id)
        if title is not None:
            feature.title = title
        if description is not None:
            feature.description = description
        return await self._features.update(feature)

    async def transition_status(self, feature_id: UUID, *, to_status: FeatureStatus) -> Feature:
        feature = await self.get_feature(feature_id)
        if not is_legal_feature_transition(feature.status, to_status):
            raise IllegalFeatureStatusTransitionError(feature.status, to_status)
        feature.status = to_status
        return await self._features.update(feature)
