"""Data access for `prompt_versions` (docs/architecture/03-db-design.md §11). Versions are
immutable once created — the only exposed mutation is `set_active()`, a narrow flip of the one
column the API design doc's own note permits changing ("the only mutation is activate")."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import PromptVariable, PromptVersion
from .models import PromptVersionModel


class PromptVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, version: PromptVersion) -> PromptVersion:
        model = _to_model(version)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, version_id: UUID) -> PromptVersion | None:
        model = await self._session.get(PromptVersionModel, version_id)
        return _to_domain(model) if model else None

    async def get_by_template_and_version_number(
        self, template_id: UUID, version_number: int
    ) -> PromptVersion | None:
        result = await self._session.execute(
            select(PromptVersionModel).where(
                PromptVersionModel.prompt_template_id == template_id,
                PromptVersionModel.version_number == version_number,
            )
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def get_active_for_template(self, template_id: UUID) -> PromptVersion | None:
        result = await self._session.execute(
            select(PromptVersionModel).where(
                PromptVersionModel.prompt_template_id == template_id,
                PromptVersionModel.is_active.is_(True),
            )
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def get_max_version_number(self, template_id: UUID) -> int:
        result = await self._session.execute(
            select(func.max(PromptVersionModel.version_number)).where(
                PromptVersionModel.prompt_template_id == template_id
            )
        )
        return result.scalar_one() or 0

    async def list_for_template(self, template_id: UUID) -> list[PromptVersion]:
        # Bounded per template in practice — a plain list, not a paginated envelope, same
        # precedent as `evaluation`'s per-run evaluation listing.
        result = await self._session.execute(
            select(PromptVersionModel)
            .where(PromptVersionModel.prompt_template_id == template_id)
            .order_by(PromptVersionModel.version_number.asc())
        )
        return [_to_domain(m) for m in result.scalars().all()]

    async def set_active(self, version_id: UUID, *, is_active: bool) -> PromptVersion:
        model = await self._session.get(PromptVersionModel, version_id)
        if model is None:
            raise ValueError(f"prompt version {version_id} does not exist — call add() first")
        model.is_active = is_active
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)


def _to_domain(model: PromptVersionModel) -> PromptVersion:
    return PromptVersion(
        id=model.id,
        prompt_template_id=model.prompt_template_id,
        version_number=model.version_number,
        content=model.content,
        created_by=model.created_by,
        variables=[PromptVariable(**v) for v in model.variables],
        is_active=model.is_active,
        created_at=model.created_at,
    )


def _to_model(version: PromptVersion) -> PromptVersionModel:
    return PromptVersionModel(
        id=version.id,
        prompt_template_id=version.prompt_template_id,
        version_number=version.version_number,
        content=version.content,
        variables=[{"name": v.name, "required": v.required} for v in version.variables],
        is_active=version.is_active,
        created_by=version.created_by,
    )
