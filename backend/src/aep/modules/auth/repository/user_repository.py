"""Data access for `users` (docs/architecture/03-db-design.md §1)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import User, UserStatus
from .models import UserModel

_SORTABLE_FIELDS = {
    "email": UserModel.email,
    "display_name": UserModel.display_name,
    "created_at": UserModel.created_at,
}


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        model = UserModel(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            auth_provider=user.auth_provider,
            auth_subject=user.auth_subject,
            status=user.status.value,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, user_id: UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_domain(model) if model else None

    async def get_by_provider_subject(self, auth_provider: str, auth_subject: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.auth_provider == auth_provider, UserModel.auth_subject == auth_subject
            )
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def list(
        self,
        *,
        status: UserStatus | None = None,
        email: str | None = None,
        sort: str = "-created_at",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        query = select(UserModel)
        count_query = select(func.count()).select_from(UserModel)
        if status is not None:
            query = query.where(UserModel.status == status.value)
            count_query = count_query.where(UserModel.status == status.value)
        if email is not None:
            query = query.where(UserModel.email == email)
            count_query = count_query.where(UserModel.email == email)

        total = (await self._session.execute(count_query)).scalar_one()

        field_name = sort.lstrip("-")
        column = _SORTABLE_FIELDS.get(field_name, UserModel.created_at)
        query = query.order_by(column.desc() if sort.startswith("-") else column.asc())
        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        return [_to_domain(m) for m in result.scalars().all()], total

    async def update(self, user: User) -> User:
        model = await self._session.get(UserModel, user.id)
        if model is None:
            raise ValueError(f"user {user.id} does not exist — call add() first")
        model.display_name = user.display_name
        model.status = user.status.value
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)


def _to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        display_name=model.display_name,
        auth_provider=model.auth_provider,
        auth_subject=model.auth_subject,
        status=UserStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
