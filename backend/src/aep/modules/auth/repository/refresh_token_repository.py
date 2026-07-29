"""Data access for `refresh_tokens` (docs/architecture/03-db-design.md §16)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import utcnow

from ..domain.models import RefreshToken
from .models import RefreshTokenModel


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, refresh_token: RefreshToken) -> RefreshToken:
        model = RefreshTokenModel(
            id=refresh_token.id,
            user_id=refresh_token.user_id,
            token_hash=refresh_token.token_hash,
            expires_at=refresh_token.expires_at,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def revoke(self, refresh_token_id: UUID) -> None:
        model = await self._session.get(RefreshTokenModel, refresh_token_id)
        if model is not None and model.revoked_at is None:
            model.revoked_at = utcnow()
            await self._session.flush()


def _to_domain(model: RefreshTokenModel) -> RefreshToken:
    return RefreshToken(
        id=model.id,
        user_id=model.user_id,
        token_hash=model.token_hash,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        created_at=model.created_at,
    )
