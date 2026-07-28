"""Data access for `features` (docs/architecture/03-db-design.md §5)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Feature, FeatureStatus
from .models import FeatureModel


class FeatureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, feature: Feature) -> Feature:
        model = _to_model(feature)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, feature_id: UUID) -> Feature | None:
        model = await self._session.get(FeatureModel, feature_id)
        return _to_domain(model) if model else None

    async def list_for_project(
        self, project_id: UUID, *, status: FeatureStatus | None = None
    ) -> list[Feature]:
        query = select(FeatureModel).where(FeatureModel.project_id == project_id)
        if status is not None:
            query = query.where(FeatureModel.status == status.value)
        query = query.order_by(FeatureModel.created_at.desc())
        result = await self._session.execute(query)
        return [_to_domain(m) for m in result.scalars().all()]

    async def update(self, feature: Feature) -> Feature:
        model = await self._session.get(FeatureModel, feature.id)
        if model is None:
            raise ValueError(f"feature {feature.id} does not exist — call add() first")
        model.title = feature.title
        model.description = feature.description
        model.status = feature.status.value
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)


def _to_domain(model: FeatureModel) -> Feature:
    return Feature(
        id=model.id,
        project_id=model.project_id,
        title=model.title,
        description=model.description,
        status=FeatureStatus(model.status),
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_model(feature: Feature) -> FeatureModel:
    return FeatureModel(
        id=feature.id,
        project_id=feature.project_id,
        title=feature.title,
        description=feature.description,
        status=feature.status.value,
        created_by=feature.created_by,
    )
