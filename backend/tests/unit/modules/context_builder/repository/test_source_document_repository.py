from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.context_builder.domain.models import SourceDocument, SourceDocumentType
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
async def repository():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield SourceDocumentRepository(session)


async def test_add_and_get_by_id_round_trips(repository: SourceDocumentRepository) -> None:
    project_id = uuid4()
    document = SourceDocument(
        id=uuid4(),
        project_id=project_id,
        doc_type=SourceDocumentType.SOURCE_FILE,
        uri="/repo/src/a.py",
        content_hash="a" * 64,
    )

    created = await repository.add(document)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.uri == "/repo/src/a.py"
    assert fetched.doc_type == SourceDocumentType.SOURCE_FILE


async def test_get_by_project_and_uri(repository: SourceDocumentRepository) -> None:
    project_id = uuid4()
    await repository.add(
        SourceDocument(
            id=uuid4(),
            project_id=project_id,
            doc_type=SourceDocumentType.SOURCE_FILE,
            uri="/repo/src/a.py",
            content_hash="a" * 64,
        )
    )

    found = await repository.get_by_project_and_uri(project_id, "/repo/src/a.py")
    missing = await repository.get_by_project_and_uri(project_id, "/repo/src/missing.py")

    assert found is not None
    assert missing is None


async def test_get_many_by_ids_returns_only_requested(repository: SourceDocumentRepository) -> None:
    project_id = uuid4()
    a = await repository.add(
        SourceDocument(
            id=uuid4(),
            project_id=project_id,
            doc_type=SourceDocumentType.SOURCE_FILE,
            uri="/repo/a.py",
            content_hash="a" * 64,
        )
    )
    await repository.add(
        SourceDocument(
            id=uuid4(),
            project_id=project_id,
            doc_type=SourceDocumentType.SOURCE_FILE,
            uri="/repo/b.py",
            content_hash="b" * 64,
        )
    )

    found = await repository.get_many_by_ids([a.id])

    assert [doc.id for doc in found] == [a.id]
    assert await repository.get_many_by_ids([]) == []


async def test_update_persists_content_hash_change(repository: SourceDocumentRepository) -> None:
    document = await repository.add(
        SourceDocument(
            id=uuid4(),
            project_id=uuid4(),
            doc_type=SourceDocumentType.SOURCE_FILE,
            uri="/repo/a.py",
            content_hash="a" * 64,
        )
    )

    document.content_hash = "b" * 64
    document.doc_type = SourceDocumentType.CODING_STANDARD
    updated = await repository.update(document)

    assert updated.content_hash == "b" * 64
    assert updated.doc_type == SourceDocumentType.CODING_STANDARD


async def test_list_for_project_filters_by_doc_type_and_scopes_to_project(
    repository: SourceDocumentRepository,
) -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    await repository.add(
        SourceDocument(
            id=uuid4(),
            project_id=project_id,
            doc_type=SourceDocumentType.SOURCE_FILE,
            uri="/repo/a.py",
            content_hash="a" * 64,
        )
    )
    standards_doc = await repository.add(
        SourceDocument(
            id=uuid4(),
            project_id=project_id,
            doc_type=SourceDocumentType.CODING_STANDARD,
            uri="/repo/CODING_STANDARDS.md",
            content_hash="b" * 64,
        )
    )
    await repository.add(
        SourceDocument(
            id=uuid4(),
            project_id=other_project_id,
            doc_type=SourceDocumentType.SOURCE_FILE,
            uri="/other/a.py",
            content_hash="c" * 64,
        )
    )

    all_docs, total = await repository.list_for_project(project_id)
    assert total == 2
    assert len(all_docs) == 2

    only_standards, standards_total = await repository.list_for_project(
        project_id, doc_type=SourceDocumentType.CODING_STANDARD
    )
    assert standards_total == 1
    assert only_standards[0].id == standards_doc.id


async def test_list_for_project_paginates_with_offset(repository: SourceDocumentRepository) -> None:
    project_id = uuid4()
    for i in range(5):
        await repository.add(
            SourceDocument(
                id=uuid4(),
                project_id=project_id,
                doc_type=SourceDocumentType.SOURCE_FILE,
                uri=f"/repo/{i}.py",
                content_hash=f"{i}" * 64,
            )
        )

    first_page, total = await repository.list_for_project(project_id, limit=2, offset=0)
    second_page, _ = await repository.list_for_project(project_id, limit=2, offset=2)

    assert total == 5
    assert len(first_page) == 2
    assert len(second_page) == 2
    assert {d.id for d in first_page}.isdisjoint({d.id for d in second_page})
