"""Context Builder orchestration: Gather -> Normalize & Chunk -> Deduplicate -> Rank ->
Budget-fit -> Assemble -> Persist (docs/architecture/06-context-builder.md §2).

Cross-module composition: resolving a task's project requires two hops through other modules'
public `services/` (never their `domain/`/`repository/`): `task_memory`'s `TaskService.get_task()`
to get `feature_id`, then `projects`' `FeatureService.get_feature()` to get `project_id` from
that — the same "call the other module's `services/`, never its `domain/`/`repository/` directly"
rule as `task_memory`'s own call into `projects`' `FeatureService` (see that module's README).
Listing source documents for a project also calls `projects`' `ProjectService.get_project()` to
confirm the project exists before listing.

Scope is deliberately narrower than the full design doc — see this module's README's "Known gaps"
section for the complete list and rationale. In short: this reference implementation ranks and
dedupes at real chunk granularity (reading actual file content, real SHA-256/Jaccard-based
dedup), but rolls the result up to *document* granularity for persistence, per the design doc's
own §10 "granularity reconciliation" rule; `structural_proximity`/`failure_history_boost` are
documented constant stand-ins (no dependency-graph gatherer or Evaluation Framework module exists
yet); and only one of the design's eight gatherers — indexed local `source_documents` — is real.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from aep.modules.projects.domain.errors import (
    FeatureNotFoundError as ProjectsFeatureNotFoundError,
)
from aep.modules.projects.domain.errors import (
    ProjectNotFoundError as ProjectsProjectNotFoundError,
)
from aep.modules.projects.services import FeatureService as ProjectsFeatureService
from aep.modules.projects.services import ProjectService as ProjectsProjectService
from aep.modules.task_memory.domain.errors import (
    TaskNotFoundError as TaskMemoryTaskNotFoundError,
)
from aep.modules.task_memory.services import TaskService as TaskMemoryTaskService

from ..domain.errors import (
    ContextPackageNotFoundError,
    FeatureNotFoundError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from ..domain.models import (
    ContextPackage,
    ContextPackageSource,
    RankingWeights,
    SourceDocument,
    SourceDocumentType,
)
from ..repository.context_package_repository import ContextPackageRepository
from ..repository.context_package_source_repository import (
    ContextPackageSourceRepository,
)
from ..repository.source_document_repository import SourceDocumentRepository
from .chunking import TextChunk, TextChunker
from .ranking import (
    DOC_TYPE_PRIOR,
    FAILURE_HISTORY_BOOST_STUB,
    RANKING_ALGORITHM_VERSION,
    SECTION_ORDER,
    STRUCTURAL_PROXIMITY_STUB,
    recency_decay,
)
from .similarity import JaccardSimilarityScorer, TextSimilarityScorer

# A generous cap on how many indexed source_documents one project's gather step considers per
# generation; a real deployment would paginate/stream rather than assume this fits in memory.
_GATHER_LIST_LIMIT = 1000

_EMPTY_CHUNK = TextChunk(text="", start_line=0, token_count=0)


@dataclass(frozen=True)
class ContextPackageSourceView:
    """A `context_package_sources` row joined with its `source_document`'s `uri`/`doc_type` —
    what docs/architecture/04-api-design.md §4's `GET .../sources` endpoint actually returns."""

    source_document_id: UUID
    uri: str
    doc_type: SourceDocumentType
    relevance_score: float
    rank: int
    included: bool
    token_count: int


@dataclass
class _ScoredChunk:
    source_document: SourceDocument
    text: str
    token_count: int
    score: float


class ContextBuilderService:
    def __init__(
        self,
        source_document_repository: SourceDocumentRepository,
        context_package_repository: ContextPackageRepository,
        context_package_source_repository: ContextPackageSourceRepository,
        task_service: TaskMemoryTaskService,
        feature_service: ProjectsFeatureService,
        project_service: ProjectsProjectService,
        *,
        similarity_scorer: TextSimilarityScorer | None = None,
        chunker: TextChunker | None = None,
        weights: RankingWeights | None = None,
        near_duplicate_threshold: float = 0.85,
    ) -> None:
        self._source_documents = source_document_repository
        self._context_packages = context_package_repository
        self._context_package_sources = context_package_source_repository
        self._tasks = task_service
        self._features = feature_service
        self._projects = project_service
        self._similarity = similarity_scorer or JaccardSimilarityScorer()
        self._chunker = chunker or TextChunker()
        self._weights = weights or RankingWeights()
        self._near_duplicate_threshold = near_duplicate_threshold

    async def generate_context_package(
        self,
        task_id: UUID,
        *,
        max_tokens: int,
        pinned_source_document_ids: set[UUID] | None = None,
    ) -> ContextPackage:
        if max_tokens <= 0:
            # The one current caller (api/router.py) already rejects this via `Field(gt=0)`
            # before it reaches here; this is a defensive invariant for any future direct caller.
            raise ValueError("max_tokens must be positive")

        try:
            task = await self._tasks.get_task(task_id)
        except TaskMemoryTaskNotFoundError as exc:
            raise TaskNotFoundError(task_id) from exc
        try:
            feature = await self._features.get_feature(task.feature_id)
        except ProjectsFeatureNotFoundError as exc:
            raise FeatureNotFoundError(task.feature_id) from exc
        project_id = feature.project_id

        pinned = pinned_source_document_ids or set()
        query_text = f"{task.title}\n{task.description or ''}"

        # Gather: the only real gatherer is indexed source_documents (services/indexing.py) —
        # related PRs / dependency graph / previous evaluations / prompt templates are documented
        # gaps (README), so this list is the entire candidate pool.
        documents, _total = await self._source_documents.list_for_project(
            project_id, limit=_GATHER_LIST_LIMIT
        )
        documents = _dedup_exact_by_content_hash(documents)

        # Normalize & Chunk, and score each chunk immediately — pure functions of (doc, chunk),
        # independent of which other chunks survive dedup.
        all_chunks: list[_ScoredChunk] = []
        for document in documents:
            content = _read_content(document.uri)
            chunks = self._chunker.chunk(content) or [_EMPTY_CHUNK]
            for chunk in chunks:
                semantic = self._similarity.score(query_text, chunk.text) if content else 0.0
                score = self._score_document(document, semantic, pinned)
                all_chunks.append(
                    _ScoredChunk(
                        source_document=document,
                        text=chunk.text,
                        token_count=chunk.token_count,
                        score=score,
                    )
                )

        # Rank (sort by score) before Deduplicate-near-duplicates, so ties between near-identical
        # chunks keep "the higher-ranked one" (design doc §5): the chunk encountered first in
        # score-descending order is, by construction, the higher scorer.
        all_chunks.sort(key=lambda c: c.score, reverse=True)
        deduped_chunks = self._dedup_near_duplicates(all_chunks)

        # Budget-fit: greedy fill in score order (design doc §8, ADR-CB3).
        included_chunks, _excluded = _fit_budget(deduped_chunks, max_tokens)
        # Identity (not equality) tracking: two chunks can legitimately share identical
        # text/score, so `id()` distinguishes "this exact chunk made the cut" from "an
        # equal-looking one did."
        included_object_ids = {id(chunk) for chunk in included_chunks}

        total_tokens = sum(chunk.token_count for chunk in included_chunks)

        package = await self._context_packages.add(
            ContextPackage(
                id=uuid4(),
                task_id=task_id,
                token_count=total_tokens,
                ranking_algorithm_version=RANKING_ALGORITHM_VERSION,
            )
        )
        # Persist: roll chunk-level results up to document granularity (design doc §10's
        # "granularity reconciliation") and assign `rank` by Assemble's fixed section order
        # (design doc §9), tie-broken by score within a section.
        entries = _build_context_package_sources(
            package.id, documents, deduped_chunks, included_object_ids
        )
        if entries:
            await self._context_package_sources.add_many(entries)
        return package

    def _score_document(
        self, document: SourceDocument, semantic_similarity: float, pinned: set[UUID]
    ) -> float:
        if document.id in pinned:
            return 1.0
        weights = self._weights
        reference_time = document.last_indexed_at or document.updated_at or document.created_at
        recency = recency_decay(reference_time) if reference_time else 0.0
        return (
            weights.semantic * semantic_similarity
            + weights.doc_type * DOC_TYPE_PRIOR.get(document.doc_type, 0.5)
            + weights.recency * recency
            + weights.structural * STRUCTURAL_PROXIMITY_STUB
            + weights.failure_history * FAILURE_HISTORY_BOOST_STUB
        )

    def _dedup_near_duplicates(self, chunks_sorted_desc: list[_ScoredChunk]) -> list[_ScoredChunk]:
        kept: list[_ScoredChunk] = []
        for chunk in chunks_sorted_desc:
            if any(
                self._similarity.score(chunk.text, k.text) >= self._near_duplicate_threshold
                for k in kept
            ):
                continue
            kept.append(chunk)
        return kept

    async def get_context_package(self, context_package_id: UUID) -> ContextPackage:
        package = await self._context_packages.get_by_id(context_package_id)
        if package is None:
            raise ContextPackageNotFoundError(context_package_id)
        return package

    async def list_context_packages_for_task(
        self, task_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[ContextPackage], int]:
        try:
            await self._tasks.get_task(task_id)
        except TaskMemoryTaskNotFoundError as exc:
            raise TaskNotFoundError(task_id) from exc
        return await self._context_packages.list_for_task(task_id, limit=limit, offset=offset)

    async def list_context_package_sources(
        self,
        context_package_id: UUID,
        *,
        included: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[ContextPackageSourceView], int]:
        await self.get_context_package(context_package_id)  # existence check -> 404 if missing
        sources, total = await self._context_package_sources.list_for_package(
            context_package_id, included=included, limit=limit, offset=offset
        )
        documents_by_id = {
            document.id: document
            for document in await self._source_documents.get_many_by_ids(
                [source.source_document_id for source in sources]
            )
        }
        views = [
            ContextPackageSourceView(
                source_document_id=source.source_document_id,
                uri=documents_by_id[source.source_document_id].uri,
                doc_type=documents_by_id[source.source_document_id].doc_type,
                relevance_score=source.relevance_score,
                rank=source.rank,
                included=source.included,
                token_count=source.token_count,
            )
            for source in sources
        ]
        return views, total

    async def list_source_documents_for_project(
        self,
        project_id: UUID,
        *,
        doc_type: SourceDocumentType | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[SourceDocument], int]:
        try:
            await self._projects.get_project(project_id)
        except ProjectsProjectNotFoundError as exc:
            raise ProjectNotFoundError(project_id) from exc
        return await self._source_documents.list_for_project(
            project_id, doc_type=doc_type, limit=limit, offset=offset
        )


def _dedup_exact_by_content_hash(documents: list[SourceDocument]) -> list[SourceDocument]:
    """Exact dedup (design doc §5, tier 1): if two catalog entries carry the same
    `content_hash`, only the first is considered — the same content indexed under two URIs (or
    returned by two gatherers) shouldn't be scored/persisted twice."""
    seen_hashes: set[str] = set()
    deduped: list[SourceDocument] = []
    for document in documents:
        if document.content_hash in seen_hashes:
            continue
        seen_hashes.add(document.content_hash)
        deduped.append(document)
    return deduped


def _read_content(uri: str) -> str:
    """`uri` for this reference implementation's indexer is an absolute local filesystem path
    (services/indexing.py). A `uri` that isn't a readable local file (e.g. a future PR gatherer's
    URL) yields empty content — the document still gets a row via non-content signals
    (doc_type_prior/recency), just with `semantic_similarity = 0`, rather than raising."""
    try:
        path = Path(uri)
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    return ""


def _fit_budget(
    chunks_sorted_desc: list[_ScoredChunk], max_tokens: int
) -> tuple[list[_ScoredChunk], list[_ScoredChunk]]:
    included: list[_ScoredChunk] = []
    excluded: list[_ScoredChunk] = []
    used_tokens = 0
    for chunk in chunks_sorted_desc:
        if used_tokens + chunk.token_count <= max_tokens:
            included.append(chunk)
            used_tokens += chunk.token_count
        else:
            excluded.append(chunk)
    return included, excluded


def _build_context_package_sources(
    context_package_id: UUID,
    documents: list[SourceDocument],
    deduped_chunks: list[_ScoredChunk],
    included_object_ids: set[int],
) -> list[ContextPackageSource]:
    chunks_by_document: dict[UUID, list[_ScoredChunk]] = {}
    for chunk in deduped_chunks:
        chunks_by_document.setdefault(chunk.source_document.id, []).append(chunk)

    rollups: list[tuple[SourceDocument, float, bool, int]] = []
    for document in documents:
        doc_chunks = chunks_by_document.get(document.id, [])
        if not doc_chunks:
            # Every one of this document's chunks was dropped as a near-duplicate of a
            # higher-scoring chunk elsewhere — nothing left to persist a row for.
            continue
        max_score = max(chunk.score for chunk in doc_chunks)
        included_doc_chunks = [c for c in doc_chunks if id(c) in included_object_ids]
        included = bool(included_doc_chunks)
        token_count = sum(c.token_count for c in included_doc_chunks)
        rollups.append((document, max_score, included, token_count))

    # Assemble's fixed section order (design doc §9) decides `rank`, not score — score only
    # breaks ties within the same section.
    rollups.sort(key=lambda item: (SECTION_ORDER.get(item[0].doc_type, 99), -item[1]))

    return [
        ContextPackageSource(
            id=uuid4(),
            context_package_id=context_package_id,
            source_document_id=document.id,
            relevance_score=round(max_score, 4),
            rank=rank,
            included=included,
            token_count=token_count,
        )
        for rank, (document, max_score, included, token_count) in enumerate(rollups, start=1)
    ]
