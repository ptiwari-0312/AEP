from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.context_builder.domain.models import SourceDocumentType
from aep.modules.context_builder.repository.source_document_repository import (
    SourceDocumentRepository,
)
from aep.modules.context_builder.services.indexing import SourceDocumentIndexer


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path_factory, monkeypatch):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
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


def _write_repo_fixture(root):
    (root / "src").mkdir()
    (root / "src" / "module.py").write_text("def handler():\n    return 1\n")
    (root / "docs").mkdir()
    (root / "docs" / "architecture").mkdir()
    (root / "docs" / "architecture" / "01-vision.md").write_text("# Vision\n")
    (root / "CODING_STANDARDS.md").write_text("# Coding Standards\n")
    (root / "notes.txt").write_text("not indexed: unsupported extension\n")


async def test_index_directory_infers_doc_type_from_path(tmp_path, repository) -> None:
    _write_repo_fixture(tmp_path)
    project_id = uuid4()
    indexer = SourceDocumentIndexer(repository)

    indexed = await indexer.index_directory(project_id, tmp_path)

    by_doc_type = {doc.doc_type: doc for doc in indexed}
    assert SourceDocumentType.SOURCE_FILE in by_doc_type
    assert SourceDocumentType.ARCHITECTURE_DOC in by_doc_type
    assert SourceDocumentType.CODING_STANDARD in by_doc_type
    # notes.txt has an extension outside the default allowlist, so it's not indexed at all.
    assert not any(doc.uri.endswith("notes.txt") for doc in indexed)


async def test_index_directory_computes_real_sha256_content_hash(tmp_path, repository) -> None:
    _write_repo_fixture(tmp_path)
    project_id = uuid4()
    indexer = SourceDocumentIndexer(repository)

    indexed = await indexer.index_directory(project_id, tmp_path)

    module_doc = next(doc for doc in indexed if doc.uri.endswith("module.py"))
    expected_hash = hashlib.sha256((tmp_path / "src" / "module.py").read_bytes()).hexdigest()
    assert module_doc.content_hash == expected_hash


async def test_reindexing_unchanged_file_does_not_bump_last_indexed_at(tmp_path, repository) -> None:
    _write_repo_fixture(tmp_path)
    project_id = uuid4()
    indexer = SourceDocumentIndexer(repository)

    first_pass = await indexer.index_directory(project_id, tmp_path)
    second_pass = await indexer.index_directory(project_id, tmp_path)

    first_module = next(doc for doc in first_pass if doc.uri.endswith("module.py"))
    second_module = next(doc for doc in second_pass if doc.uri.endswith("module.py"))
    assert first_module.id == second_module.id
    assert first_module.last_indexed_at == second_module.last_indexed_at


async def test_reindexing_changed_file_updates_content_hash(tmp_path, repository) -> None:
    _write_repo_fixture(tmp_path)
    project_id = uuid4()
    indexer = SourceDocumentIndexer(repository)

    first_pass = await indexer.index_directory(project_id, tmp_path)
    first_module = next(doc for doc in first_pass if doc.uri.endswith("module.py"))

    (tmp_path / "src" / "module.py").write_text("def handler():\n    return 2\n")
    second_pass = await indexer.index_directory(project_id, tmp_path)
    second_module = next(doc for doc in second_pass if doc.uri.endswith("module.py"))

    assert second_module.id == first_module.id
    assert second_module.content_hash != first_module.content_hash


async def test_index_directory_upserts_by_project_and_uri(tmp_path, repository) -> None:
    _write_repo_fixture(tmp_path)
    project_id = uuid4()
    indexer = SourceDocumentIndexer(repository)

    await indexer.index_directory(project_id, tmp_path)
    documents, total = await repository.list_for_project(project_id, limit=100)

    # 3 indexable files: module.py, 01-vision.md, CODING_STANDARDS.md — notes.txt is excluded.
    assert total == 3
    assert len(documents) == 3
