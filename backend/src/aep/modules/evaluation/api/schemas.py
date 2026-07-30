"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §7 —
no DB or provider calls in this layer (docs/architecture/02-repo-design.md §2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import EvaluationStatus, EvaluatorType


class TriggerEvaluationsRequest(BaseModel):
    evaluator_types: list[EvaluatorType] = Field(min_length=1)


class TriggerEvaluationsResponse(BaseModel):
    # Per docs/architecture/04-api-design.md §7 this is async (`status: "queued"`, "run in
    # parallel by the Evaluation Framework's plugin runner"). Every evaluator registered in this
    # reference backend (PerformanceEvaluator, EchoJudgeEvaluator) is fully synchronous — no
    # external platform call, no PENDING_EXTERNAL status ever returned — so triggering completes
    # within the request. Same documented deviation as context_builder's
    # `GenerateContextPackageResponse`: `evaluation_ids` are real and immediately fetchable, and
    # `status` is always `"completed"`, never a `"queued"` a caller would poll forever.
    evaluation_ids: list[str]
    status: Literal["completed"] = "completed"


class EvaluationResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric_name: str
    score: float
    threshold: float | None
    passed: bool
    details: dict[str, Any]


class EvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_run_id: UUID
    evaluator_type: EvaluatorType
    status: EvaluationStatus
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime | None


class QualityGateEvaluationResponse(BaseModel):
    evaluator_type: EvaluatorType
    status: EvaluationStatus
    results: list[EvaluationResultResponse]


class QualityGateResponse(BaseModel):
    task_id: UUID
    agent_run_id: UUID | None
    overall: Literal["passed", "failed", "pending"]
    evaluations: list[QualityGateEvaluationResponse]
