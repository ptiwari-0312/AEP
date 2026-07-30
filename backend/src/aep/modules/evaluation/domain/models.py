"""Pure domain entities and value objects for the Evaluation Framework
(docs/architecture/03-db-design.md §14-15; docs/architecture/07-evaluation-framework.md;
docs/architecture/02-repo-design.md §2's domain/ layer — zero framework imports).

`EvaluatorType`/`EvaluationStatus` are imported from `aep_eval_sdk` rather than redefined here —
they're the SDK's own contract (`BaseEvaluator.evaluator_type`, `EvaluationReport.status`), and
this module's `evaluations` table exists to persist instances of those same enums, not parallel
ones that could drift out of sync with them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from aep_eval_sdk import EvaluationStatus, EvaluatorType

__all__ = [
    "Evaluation",
    "EvaluationResult",
    "EvaluationStatus",
    "EvaluatorType",
    "QualityGateEvaluationSummary",
    "QualityGateResult",
]


@dataclass
class Evaluation:
    id: UUID
    agent_run_id: UUID
    evaluator_type: EvaluatorType
    status: EvaluationStatus = EvaluationStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None


@dataclass
class EvaluationResult:
    id: UUID
    evaluation_id: UUID
    metric_name: str
    score: float
    passed: bool
    threshold: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class QualityGateEvaluationSummary:
    evaluator_type: EvaluatorType
    status: EvaluationStatus
    results: list[EvaluationResult]


@dataclass
class QualityGateResult:
    """docs/architecture/04-api-design.md §7's `GET /tasks/{taskId}/quality-gate` response —
    computed on read, never persisted (§7's own framing: "the gate itself is computed, not
    stored"). `agent_run_id` is `None` when the task has no runs yet, a legitimate "nothing to
    gate" state rather than an error."""

    task_id: UUID
    agent_run_id: UUID | None
    overall: Literal["passed", "failed", "pending"]
    evaluations: list[QualityGateEvaluationSummary]
