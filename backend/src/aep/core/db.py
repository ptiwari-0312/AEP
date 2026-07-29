"""SQLAlchemy async session/engine management (docs/architecture/02-repo-design.md §2).

`modules/*/repository` depends on this and nothing else in `core/` for persistence
(docs/architecture/02-repo-design.md §2's dependency table).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
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


def utcnow() -> datetime:
    """The shared `created_at`/`updated_at` default every module's models should use, instead
    of `server_default=func.now()`. On SQLite, `CURRENT_TIMESTAMP` stores "YYYY-MM-DD HH:MM:SS"
    (no microseconds), but SQLAlchemy's `DateTime` bind processor always formats a
    Python-supplied datetime WITH microseconds — on SQLite's TEXT-affinity storage that mismatch
    means `created_at == <python datetime>` silently never matches, which breaks keyset/cursor
    pagination on any tie (discovered the hard way building the Task Memory module). Using this
    Python-side default everywhere keeps the stored value and any later comparison on the same
    formatting path, on every backend, not just Postgres where the native TIMESTAMP type would
    have papered over it."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalizes a datetime that may have lost its `tzinfo` on a round trip through SQLite —
    confirmed empirically: a tz-aware datetime stored via SQLAlchemy's `DateTime` type comes
    back from SQLite as naive (Postgres's native `TIMESTAMPTZ` round-trips it correctly; this
    is a SQLite-testing-only gap, not one every backend has). Comparing a DB-round-tripped
    value directly against a freshly-computed `utcnow()` then raises
    `TypeError: can't compare offset-naive and offset-aware datetimes`. Every datetime this app
    produces is UTC by convention (via `utcnow()`), so a naive value is assumed to already be
    UTC — not the local timezone — rather than silently misinterpreted."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


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
