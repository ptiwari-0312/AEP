from __future__ import annotations

import inspect

import pytest
from sqlalchemy import Column, Integer, String, select

from aep.core.config import get_settings
from aep.core.db import Base, get_db_session, get_engine, get_session_factory


class _Widget(Base):
    __tablename__ = "widgets_test_fixture"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


@pytest.fixture(autouse=True)
def _sqlite_backed_settings(tmp_path, monkeypatch):
    # A real file-backed SQLite DB, not `:memory:` — an in-memory SQLite DB is isolated per
    # connection unless a shared-cache/StaticPool workaround is added, which would make this
    # test exercise SQLite-specific pooling quirks rather than get_db_session's actual
    # commit/rollback behavior. A temp file behaves like a real database across connections,
    # same as Postgres would.
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEP_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


async def _create_schema() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def test_get_db_session_commits_on_success() -> None:
    await _create_schema()

    session_gen = get_db_session()
    session = await anext(session_gen)
    session.add(_Widget(name="alpha"))
    with pytest.raises(StopAsyncIteration):
        await anext(session_gen)

    async with get_session_factory()() as verify_session:
        result = await verify_session.execute(select(_Widget))
        assert [row.name for row in result.scalars().all()] == ["alpha"]


async def test_get_db_session_rolls_back_on_exception() -> None:
    await _create_schema()

    session_gen = get_db_session()
    session = await anext(session_gen)
    session.add(_Widget(name="should-not-persist"))

    with pytest.raises(RuntimeError, match="boom"):
        await session_gen.athrow(RuntimeError("boom"))

    async with get_session_factory()() as verify_session:
        result = await verify_session.execute(select(_Widget))
        assert result.scalars().all() == []


def test_get_db_session_takes_no_arguments() -> None:
    assert inspect.isasyncgenfunction(get_db_session)
    assert list(inspect.signature(get_db_session).parameters) == []
