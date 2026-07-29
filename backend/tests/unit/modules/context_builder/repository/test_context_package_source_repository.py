from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.context_builder.domain.models import (
    ContextPackage,
    ContextPackageSource,
    SourceDocument,
    SourceDocumentType,
)
from aep.modules.context_builder.repository.context_package_repository import (
    ContextPackageRepository,
)
from aep.modules.context_builder.repository.context_package_source_repository import (
    ContextPackageSourceRepository,
)
from aep.modules.context_builder.repository.source_document_repository import (
    SourceDocumentRepository,
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
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
async def package(session) -> ContextPackage:
    return await ContextPackageRepository(session).add(
        ContextPackage(
            id=uuid4(), task_id=uuid4(), token_count=0, ranking_algorithm_version="v1"
        )
    )


@pytest.fixture
async def documents(session) -> list[SourceDocument]:
    repo = SourceDocumentRepository(session)
    project_id = uuid4()
    return [
        await repo.add(
            SourceDocument(
                id=uuid4(),
                project_id=project_id,
                doc_type=SourceDocumentType.SOURCE_FILE,
                uri=f"/repo/{i}.py",
                content_hash=f"{i}" * 64,
            )
        )
        for i in range(3)
    ]


async def test_add_many_and_list_for_package_sorted_by_rank(session, package, documents) -> None:
    repo = ContextPackageSourceRepository(session)
    entries = [
        ContextPackageSource(
            id=uuid4(),
            context_package_id=package.id,
            source_document_id=documents[i].id,
            relevance_score=0.9 - i * 0.1,
            rank=3 - i,
            included=True,
            token_count=50,
        )
        for i in range(3)
    ]

    await repo.add_many(entries)
    fetched, total = await repo.list_for_package(package.id)

    assert total == 3
    assert [s.rank for s in fetched] == [1, 2, 3]


async def test_list_for_package_filters_by_included(session, package, documents) -> None:
    repo = ContextPackageSourceRepository(session)
    await repo.add_many(
        [
            ContextPackageSource(
                id=uuid4(),
                context_package_id=package.id,
                source_document_id=documents[0].id,
                relevance_score=0.9,
                rank=1,
                included=True,
                token_count=50,
            ),
            ContextPackageSource(
                id=uuid4(),
                context_package_id=package.id,
                source_document_id=documents[1].id,
                relevance_score=0.1,
                rank=2,
                included=False,
                token_count=0,
            ),
        ]
    )

    included_only, included_total = await repo.list_for_package(package.id, included=True)
    excluded_only, excluded_total = await repo.list_for_package(package.id, included=False)

    assert included_total == 1
    assert excluded_total == 1
    assert included_only[0].source_document_id == documents[0].id
    assert excluded_only[0].source_document_id == documents[1].id
