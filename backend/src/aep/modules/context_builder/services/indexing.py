"""Gather, source-document side (docs/architecture/06-context-builder.md §3, §11).

Of the design doc's eight gatherer sources, this reference implementation builds exactly one for
real: a local-filesystem indexer that walks an actual directory (e.g. a cloned git repo checkout
on the same machine as the backend process — a reasonable assumption for a reference deployment,
and the only one that requires no external network/API dependency), computing a real SHA-256
`content_hash` per file and upserting `source_documents` rows keyed on `(project_id, uri)`.

The other seven — architecture docs/coding standards/API specs (all really the same "local file"
gatherer, distinguished only by `doc_type` inference below), related pull requests (needs a real
GitHub API integration), the dependency graph (needs real import-graph static analysis),
previous evaluations (needs the Evaluation Framework module, which doesn't exist in `backend/`
yet), and prompt templates (needs the Prompt Library module) — are not built. This module's
README documents each as a deliberate gap, the same pattern as `task_memory`'s deferred
`task-graph:generate` endpoint.

Re-indexing here runs on demand (call `index_directory()` directly, e.g. from a scheduled job or
a repo webhook handler), not from an HTTP endpoint — docs/architecture/04-api-design.md §4 has no
indexing endpoint of its own; `source_documents` is described as populated by a background
process the API only reads from.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID, uuid4

from aep.core.db import utcnow

from ..domain.models import SourceDocument, SourceDocumentType
from ..repository.source_document_repository import SourceDocumentRepository

_DEFAULT_EXTENSIONS = {".py", ".md", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml"}

# Path-substring hints, checked in order — first match wins, falling back to SOURCE_FILE.
# A real deployment would want richer/configurable rules; this is enough to distinguish this
# very repo's own architecture docs and coding-standards doc from ordinary source files, which is
# what the test suite indexes against.
_DOC_TYPE_PATH_HINTS: tuple[tuple[str, SourceDocumentType], ...] = (
    ("architecture", SourceDocumentType.ARCHITECTURE_DOC),
    ("coding_standard", SourceDocumentType.CODING_STANDARD),
    ("coding-standard", SourceDocumentType.CODING_STANDARD),
    ("api-design", SourceDocumentType.API_SPEC),
    ("api_spec", SourceDocumentType.API_SPEC),
    ("openapi", SourceDocumentType.API_SPEC),
)


def _infer_doc_type(relative_path: Path) -> SourceDocumentType:
    normalized = str(relative_path).replace("\\", "/").lower()
    for hint, doc_type in _DOC_TYPE_PATH_HINTS:
        if hint in normalized:
            return doc_type
    return SourceDocumentType.SOURCE_FILE


class SourceDocumentIndexer:
    def __init__(self, repository: SourceDocumentRepository) -> None:
        self._repository = repository

    async def index_directory(
        self,
        project_id: UUID,
        root_path: Path,
        *,
        extensions: set[str] | None = None,
    ) -> list[SourceDocument]:
        allowed_extensions = extensions or _DEFAULT_EXTENSIONS
        indexed: list[SourceDocument] = []
        for path in sorted(root_path.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed_extensions:
                continue
            indexed.append(await self._index_file(project_id, root_path, path))
        return indexed

    async def _index_file(self, project_id: UUID, root_path: Path, path: Path) -> SourceDocument:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        uri = str(path.resolve())
        doc_type = _infer_doc_type(path.relative_to(root_path))

        existing = await self._repository.get_by_project_and_uri(project_id, uri)
        if existing is None:
            return await self._repository.add(
                SourceDocument(
                    id=uuid4(),
                    project_id=project_id,
                    doc_type=doc_type,
                    uri=uri,
                    content_hash=content_hash,
                    last_indexed_at=utcnow(),
                )
            )
        if existing.content_hash == content_hash:
            # Unchanged since last index — content_hash is the cache-invalidation key (DB design
            # §13); no write needed.
            return existing
        existing.content_hash = content_hash
        existing.doc_type = doc_type
        existing.last_indexed_at = utcnow()
        return await self._repository.update(existing)
