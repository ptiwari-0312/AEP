from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.context_builder.domain.models import ContextPackage
from aep.modules.context_builder.repository.context_package_repository import (
    ContextPackageRepository,
)


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEP_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
async def repository():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield ContextPackageRepository(session)


async def test_add_and_get_by_id_round_trips(repository: ContextPackageRepository) -> None:
    task_id = uuid4()
    package = ContextPackage(
        id=uuid4(), task_id=task_id, token_count=1234, ranking_algorithm_version="v1"
    )

    created = await repository.add(package)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.task_id == task_id
    assert fetched.token_count == 1234
    assert fetched.generated_at is not None


async def test_get_by_id_returns_none_when_missing(repository: ContextPackageRepository) -> None:
    assert await repository.get_by_id(uuid4()) is None


async def test_list_for_task_scopes_and_paginates(repository: ContextPackageRepository) -> None:
    task_id = uuid4()
    other_task_id = uuid4()
    for _ in range(3):
        await repository.add(
            ContextPackage(
                id=uuid4(), task_id=task_id, token_count=100, ranking_algorithm_version="v1"
            )
        )
    await repository.add(
        ContextPackage(
            id=uuid4(), task_id=other_task_id, token_count=100, ranking_algorithm_version="v1"
        )
    )

    packages, total = await repository.list_for_task(task_id, limit=2, offset=0)

    assert total == 3
    assert len(packages) == 2
    assert all(p.task_id == task_id for p in packages)
