"""Data access for `context_package_sources` (docs/architecture/03-db-design.md §16)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import ContextPackageSource
from .models import ContextPackageSourceModel


class ContextPackageSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(
        self, sources: list[ContextPackageSource]
    ) -> list[ContextPackageSource]:
        models = [_to_model(source) for source in sources]
        self._session.add_all(models)
        await self._session.flush()
        for model in models:
            await self._session.refresh(model)
        return [_to_domain(m) for m in models]

    async def list_for_package(
        self,
        context_package_id: UUID,
        *,
        included: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ContextPackageSource], int]:
        query = select(ContextPackageSourceModel).where(
            ContextPackageSourceModel.context_package_id == context_package_id
        )
        count_query = (
            select(func.count())
            .select_from(ContextPackageSourceModel)
            .where(ContextPackageSourceModel.context_package_id == context_package_id)
        )
        if included is not None:
            query = query.where(ContextPackageSourceModel.included == included)
            count_query = count_query.where(ContextPackageSourceModel.included == included)

        total = (await self._session.execute(count_query)).scalar_one()

        # `sort=rank` per docs/architecture/04-api-design.md §4 — the only sort this endpoint's
        # contract offers, so it's fixed rather than exposed as a query param.
        query = query.order_by(ContextPackageSourceModel.rank.asc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [_to_domain(m) for m in result.scalars().all()], total


def _to_domain(model: ContextPackageSourceModel) -> ContextPackageSource:
    return ContextPackageSource(
        id=model.id,
        context_package_id=model.context_package_id,
        source_document_id=model.source_document_id,
        relevance_score=model.relevance_score,
        rank=model.rank,
        included=model.included,
        token_count=model.token_count,
    )


def _to_model(source: ContextPackageSource) -> ContextPackageSourceModel:
    return ContextPackageSourceModel(
        id=source.id,
        context_package_id=source.context_package_id,
        source_document_id=source.source_document_id,
        relevance_score=source.relevance_score,
        rank=source.rank,
        included=source.included,
        token_count=source.token_count,
    )
