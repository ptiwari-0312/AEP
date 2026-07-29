"""Rank (docs/architecture/06-context-builder.md §6-7, ADR-CB1).

`score(chunk) = w1*semantic_similarity + w2*structural_proximity + w3*recency_decay +
w4*doc_type_prior + w5*failure_history_boost`, with `pinned_override` short-circuiting to the
max score when set. `semantic_similarity` and `recency_decay` are real, computed signals
(`similarity.py`, `recency_decay()` below); `doc_type_prior` is a real fixed lookup table.
`structural_proximity` and `failure_history_boost` are documented stand-ins, not real signals —
see the module README's "Known gaps" section for why each can't be computed for real yet
(no dependency-graph gatherer, no Evaluation Framework module). Both default to a neutral
constant and are weighted low by `RankingWeights`' defaults, rather than zeroed outright, so the
formula's shape matches the design doc exactly and either can be swapped for a real
implementation later without changing the scoring function's signature.
"""

from __future__ import annotations

from datetime import datetime

from aep.core.db import ensure_utc, utcnow

from ..domain.models import SourceDocumentType

RANKING_ALGORITHM_VERSION = "context-builder-v1-jaccard"

# "Coding standards and architecture docs are close to always relevant regardless of textual
# similarity to one task — this is what keeps them from getting starved out by more 'on-topic'-
# looking source chunks" (design doc §6). Fixed baseline per doc_type; tunable only by editing
# this table (the design doc frames it as configuration, but a per-project override store doesn't
# exist yet — this is the reference default).
DOC_TYPE_PRIOR: dict[SourceDocumentType, float] = {
    SourceDocumentType.CODING_STANDARD: 0.90,
    SourceDocumentType.ARCHITECTURE_DOC: 0.85,
    SourceDocumentType.API_SPEC: 0.75,
    SourceDocumentType.EVALUATION_HISTORY: 0.55,
    SourceDocumentType.DEPENDENCY_GRAPH: 0.60,
    SourceDocumentType.SOURCE_FILE: 0.50,
    SourceDocumentType.PULL_REQUEST: 0.45,
    SourceDocumentType.PROMPT_TEMPLATE: 0.0,  # never scored — see SECTION_ORDER's docstring
}

# Assemble's fixed section order (design doc §9) — used both to order the final package and to
# assign `context_package_sources.rank` (DB design §16), since the persisted schema doesn't
# separately record "assembly position" from "rank".
SECTION_ORDER: dict[SourceDocumentType, int] = {
    SourceDocumentType.CODING_STANDARD: 1,
    SourceDocumentType.ARCHITECTURE_DOC: 2,
    SourceDocumentType.API_SPEC: 3,
    SourceDocumentType.DEPENDENCY_GRAPH: 4,
    SourceDocumentType.SOURCE_FILE: 5,
    SourceDocumentType.PULL_REQUEST: 6,
    SourceDocumentType.EVALUATION_HISTORY: 7,
    SourceDocumentType.PROMPT_TEMPLATE: 8,
}

# Neither the dependency-graph gatherer (ADR-CB5's N-hop subgraph) nor the Evaluation Framework
# module exist in `backend/` yet, so these two signals can't be computed for real. A neutral
# constant (rather than 0) keeps a document with no other distinguishing signal from being
# penalized purely for a gap in this reference implementation, not in the document itself.
STRUCTURAL_PROXIMITY_STUB = 0.5
FAILURE_HISTORY_BOOST_STUB = 0.0

_RECENCY_HALF_LIFE_DAYS = 30.0


def recency_decay(reference_time: datetime, *, half_life_days: float = _RECENCY_HALF_LIFE_DAYS) -> float:
    """Exponential decay by age: `0.5 ** (age_days / half_life_days)`, so a document exactly one
    half-life old scores 0.5, bounded to (0, 1]."""
    age_days = max(0.0, (utcnow() - ensure_utc(reference_time)).total_seconds() / 86400)
    return 0.5 ** (age_days / half_life_days)
