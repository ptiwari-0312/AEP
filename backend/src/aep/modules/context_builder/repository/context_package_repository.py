"""Data access for `context_packages` (docs/architecture/03-db-design.md §12)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import ContextPackage
from .models import ContextPackageModel


class ContextPackageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, package: ContextPackage) -> ContextPackage:
        model = _to_model(package)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, context_package_id: UUID) -> ContextPackage | None:
        model = await self._session.get(ContextPackageModel, context_package_id)
        return _to_domain(model) if model else None

    async def list_for_task(
        self, task_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[ContextPackage], int]:
        query = select(ContextPackageModel).where(ContextPackageModel.task_id == task_id)
        count_query = (
            select(func.count())
            .select_from(ContextPackageModel)
            .where(ContextPackageModel.task_id == task_id)
        )
        total = (await self._session.execute(count_query)).scalar_one()

        query = query.order_by(ContextPackageModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [_to_domain(m) for m in result.scalars().all()], total


def _to_domain(model: ContextPackageModel) -> ContextPackage:
    return ContextPackage(
        id=model.id,
        task_id=model.task_id,
        token_count=model.token_count,
        ranking_algorithm_version=model.ranking_algorithm_version,
        generated_at=model.generated_at,
        created_at=model.created_at,
    )


def _to_model(package: ContextPackage) -> ContextPackageModel:
    return ContextPackageModel(
        id=package.id,
        task_id=package.task_id,
        token_count=package.token_count,
        ranking_algorithm_version=package.ranking_algorithm_version,
    )
