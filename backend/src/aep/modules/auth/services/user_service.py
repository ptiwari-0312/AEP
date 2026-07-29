"""Use-case orchestration for Users and Roles (docs/architecture/04-api-design.md §1)."""

from __future__ import annotations

from uuid import UUID

from ..domain.errors import (
    RoleAlreadyGrantedError,
    RoleNotFoundError,
    RoleNotGrantedError,
    UserNotFoundError,
)
from ..domain.models import Role, User, UserRole, UserStatus
from ..repository.role_repository import RoleRepository
from ..repository.user_repository import UserRepository


class UserService:
    def __init__(self, user_repository: UserRepository, role_repository: RoleRepository) -> None:
        self._users = user_repository
        self._roles = role_repository

    async def get_user(self, user_id: UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        user.roles = await self._roles.list_role_names_for_user(user_id)
        return user

    async def list_users(
        self,
        *,
        status: UserStatus | None = None,
        email: str | None = None,
        sort: str = "-created_at",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        return await self._users.list(status=status, email=email, sort=sort, limit=limit, offset=offset)

    async def update_user(
        self, user_id: UUID, *, display_name: str | None = None, status: UserStatus | None = None
    ) -> User:
        user = await self.get_user(user_id)
        if display_name is not None:
            user.display_name = display_name
        if status is not None:
            user.status = status
        return await self._users.update(user)

    async def list_roles(self) -> list[Role]:
        return await self._roles.list_all()

    async def grant_role(
        self, user_id: UUID, *, role_id: UUID, granted_by: UUID | None = None
    ) -> UserRole:
        if await self._users.get_by_id(user_id) is None:
            raise UserNotFoundError(user_id)
        if await self._roles.get_by_id(role_id) is None:
            raise RoleNotFoundError(role_id)
        if await self._roles.has_role(user_id, role_id):
            raise RoleAlreadyGrantedError(user_id, role_id)
        return await self._roles.grant(user_id, role_id, granted_by=granted_by)

    async def revoke_role(self, user_id: UUID, role_id: UUID) -> None:
        if await self._users.get_by_id(user_id) is None:
            raise UserNotFoundError(user_id)
        if await self._roles.get_by_id(role_id) is None:
            raise RoleNotFoundError(role_id)
        if not await self._roles.has_role(user_id, role_id):
            raise RoleNotGrantedError(user_id, role_id)
        await self._roles.revoke(user_id, role_id)
