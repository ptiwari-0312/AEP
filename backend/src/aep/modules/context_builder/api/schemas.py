"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §4 —
no DB or provider calls in this layer (docs/architecture/02-repo-design.md §2)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import SourceDocumentType


class GenerateContextPackageRequest(BaseModel):
    max_tokens: int = Field(gt=0)
    force_reindex: bool = False


class GenerateContextPackageResponse(BaseModel):
    # Per docs/architecture/04-api-design.md §4 this is async (`job_id` + `status: "queued"`),
    # since generation "involves ranking and possibly re-embedding documents." This reference
    # implementation's ranking has no embedding/LLM call in it (docs/architecture/
    # 06-context-builder.md §13 explicitly puts the embedding model out of scope), so it
    # completes synchronously within the request — `job_id` is the real `context_package_id`
    # (fetchable immediately via `GET /context-packages/{id}`), and `status` is always
    # `"completed"` rather than a `"queued"` a caller would poll forever. See this module's
    # README for the full rationale.
    job_id: str
    status: Literal["completed"] = "completed"


class ContextPackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    token_count: int
    ranking_algorithm_version: str
    generated_at: datetime | None
    created_at: datetime | None


class ContextPackageListResponse(BaseModel):
    items: list[ContextPackageResponse]
    page: int
    page_size: int
    total: int


class ContextPackageSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_document_id: UUID
    uri: str
    doc_type: SourceDocumentType
    relevance_score: float
    rank: int
    included: bool
    token_count: int


class ContextPackageSourceListResponse(BaseModel):
    items: list[ContextPackageSourceResponse]
    page: int
    page_size: int
    total: int


class SourceDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    doc_type: SourceDocumentType
    uri: str
    content_hash: str
    last_indexed_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None


class SourceDocumentListResponse(BaseModel):
    items: list[SourceDocumentResponse]
    page: int
    page_size: int
    total: int
