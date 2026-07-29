"""Pure domain entities and value objects for the Context Builder
(docs/architecture/03-db-design.md §12-13, §16; docs/architecture/06-context-builder.md;
docs/architecture/02-repo-design.md §2's domain/ layer — zero framework imports).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class SourceDocumentType(str, Enum):
    SOURCE_FILE = "source_file"
    ARCHITECTURE_DOC = "architecture_doc"
    CODING_STANDARD = "coding_standard"
    API_SPEC = "api_spec"
    PULL_REQUEST = "pull_request"
    DEPENDENCY_GRAPH = "dependency_graph"
    EVALUATION_HISTORY = "evaluation_history"
    PROMPT_TEMPLATE = "prompt_template"


@dataclass
class SourceDocument:
    id: UUID
    project_id: UUID
    doc_type: SourceDocumentType
    uri: str
    content_hash: str
    last_indexed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class ContextPackage:
    id: UUID
    task_id: UUID
    token_count: int
    ranking_algorithm_version: str
    generated_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class ContextPackageSource:
    id: UUID
    context_package_id: UUID
    source_document_id: UUID
    relevance_score: float
    rank: int
    included: bool = True
    token_count: int = 0


@dataclass(frozen=True)
class RankingWeights:
    """`w1..w5` from docs/architecture/06-context-builder.md §6's scoring formula — configuration,
    not a hardcoded constant, so a project/task-type can tune them without a code change (per the
    design doc's own framing). Defaults sum to 1.0 for interpretability, but nothing enforces that.
    """

    semantic: float = 0.35
    doc_type: float = 0.30
    recency: float = 0.20
    structural: float = 0.10
    failure_history: float = 0.05
