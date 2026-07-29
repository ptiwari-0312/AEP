"""Data access for `roles` and `user_roles` (docs/architecture/03-db-design.md §2, §16)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Role, UserRole
from .models import RoleModel, UserRoleModel


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, role_id: UUID) -> Role | None:
        model = await self._session.get(RoleModel, role_id)
        return _to_domain(model) if model else None

    async def get_by_name(self, name: str) -> Role | None:
        result = await self._session.execute(select(RoleModel).where(RoleModel.name == name))
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def list_all(self) -> list[Role]:
        result = await self._session.execute(select(RoleModel).order_by(RoleModel.name.asc()))
        return [_to_domain(m) for m in result.scalars().all()]

    async def list_role_names_for_user(self, user_id: UUID) -> list[str]:
        result = await self._session.execute(
            select(RoleModel.name)
            .join(UserRoleModel, UserRoleModel.role_id == RoleModel.id)
            .where(UserRoleModel.user_id == user_id)
        )
        return list(result.scalars().all())

    async def has_role(self, user_id: UUID, role_id: UUID) -> bool:
        result = await self._session.execute(
            select(UserRoleModel).where(
                UserRoleModel.user_id == user_id, UserRoleModel.role_id == role_id
            )
        )
        return result.scalar_one_or_none() is not None

    async def grant(self, user_id: UUID, role_id: UUID, *, granted_by: UUID | None) -> UserRole:
        model = UserRoleModel(user_id=user_id, role_id=role_id, granted_by=granted_by)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return UserRole(
            user_id=model.user_id,
            role_id=model.role_id,
            granted_at=model.granted_at,
            granted_by=model.granted_by,
        )

    async def revoke(self, user_id: UUID, role_id: UUID) -> None:
        model = await self._session.get(UserRoleModel, (user_id, role_id))
        if model is not None:
            await self._session.delete(model)
            await self._session.flush()


def _to_domain(model: RoleModel) -> Role:
    return Role(id=model.id, name=model.name, description=model.description, created_at=model.created_at)
