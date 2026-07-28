"""SQLAlchemy async session/engine management (docs/architecture/02-repo-design.md §2).

`modules/*/repository` depends on this and nothing else in `core/` for persistence
(docs/architecture/02-repo-design.md §2's dependency table).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import Settings, get_settings


class Base(DeclarativeBase):
    """The declarative base every module's `repository/` models inherit from."""


@lru_cache
def get_engine(database_url: str | None = None) -> AsyncEngine:
    """Cached by URL so tests can point at a throwaway SQLite database without disturbing the
    cached production engine (`get_engine.cache_clear()` between tests that vary the URL)."""
    url = database_url or get_settings().database_url
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def get_session_factory(database_url: str | None = None) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(database_url), expire_on_commit=False)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request — committed on success, rolled back and
    re-raised on any exception, always closed via the `async with` block regardless."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine(settings: Settings | None = None) -> None:
    """Called on application shutdown to close the connection pool cleanly."""
    engine = get_engine((settings or get_settings()).database_url)
    await engine.dispose()
