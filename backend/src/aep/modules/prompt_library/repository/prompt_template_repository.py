"""Data access for `prompt_templates` (docs/architecture/03-db-design.md §10)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import PromptTemplate
from .models import PromptTemplateModel


class PromptTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, template: PromptTemplate) -> PromptTemplate:
        model = _to_model(template)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, template_id: UUID) -> PromptTemplate | None:
        model = await self._session.get(PromptTemplateModel, template_id)
        return _to_domain(model) if model else None

    async def get_by_name(self, name: str) -> PromptTemplate | None:
        result = await self._session.execute(
            select(PromptTemplateModel).where(PromptTemplateModel.name == name)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def list(self, *, limit: int = 20, offset: int = 0) -> tuple[list[PromptTemplate], int]:
        total = (await self._session.execute(select(func.count()).select_from(PromptTemplateModel))).scalar_one()
        result = await self._session.execute(
            select(PromptTemplateModel)
            .order_by(PromptTemplateModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_to_domain(m) for m in result.scalars().all()], total


def _to_domain(model: PromptTemplateModel) -> PromptTemplate:
    return PromptTemplate(
        id=model.id,
        name=model.name,
        description=model.description,
        owner_user_id=model.owner_user_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_model(template: PromptTemplate) -> PromptTemplateModel:
    return PromptTemplateModel(
        id=template.id,
        name=template.name,
        description=template.description,
        owner_user_id=template.owner_user_id,
    )
