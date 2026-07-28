"""Data types exchanged across the BaseEvaluator lifecycle
(docs/architecture/07-evaluation-framework.md §2)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvaluatorType(str, Enum):
    """The twelve evaluator types from docs/architecture/07-evaluation-framework.md, matching
    the `evaluations.evaluator_type` DB check constraint (docs/architecture/03-db-design.md §14)."""

    DEEPEVAL = "deepeval"
    PROMPTFOO = "promptfoo"
    LLM_JUDGE = "llm_judge"
    BRAINTRUST = "braintrust"
    LANGFUSE = "langfuse"
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    SECURITY_SCAN = "security_scan"
    STATIC_ANALYSIS = "static_analysis"
    COVERAGE = "coverage"
    PERFORMANCE = "performance"
    ARCHITECTURE_RULES = "architecture_rules"


class EvaluatorCategory(str, Enum):
    """docs/architecture/07-evaluation-framework.md §3 — drives fail-fast scheduling in the
    backend's Evaluation Runner; carried here since it's a property of the evaluator type
    itself, not something the Runner should hardcode per type."""

    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"


_CATEGORY_BY_TYPE: dict[EvaluatorType, EvaluatorCategory] = {
    EvaluatorType.UNIT_TEST: EvaluatorCategory.DETERMINISTIC,
    EvaluatorType.INTEGRATION_TEST: EvaluatorCategory.DETERMINISTIC,
    EvaluatorType.STATIC_ANALYSIS: EvaluatorCategory.DETERMINISTIC,
    EvaluatorType.COVERAGE: EvaluatorCategory.DETERMINISTIC,
    EvaluatorType.PERFORMANCE: EvaluatorCategory.DETERMINISTIC,
    EvaluatorType.ARCHITECTURE_RULES: EvaluatorCategory.DETERMINISTIC,
    EvaluatorType.SECURITY_SCAN: EvaluatorCategory.DETERMINISTIC,
    EvaluatorType.DEEPEVAL: EvaluatorCategory.LLM_ASSISTED,
    EvaluatorType.PROMPTFOO: EvaluatorCategory.LLM_ASSISTED,
    EvaluatorType.LLM_JUDGE: EvaluatorCategory.LLM_ASSISTED,
    EvaluatorType.BRAINTRUST: EvaluatorCategory.LLM_ASSISTED,
    EvaluatorType.LANGFUSE: EvaluatorCategory.LLM_ASSISTED,
}


def category_of(evaluator_type: EvaluatorType) -> EvaluatorCategory:
    return _CATEGORY_BY_TYPE[evaluator_type]


class EvaluationStatus(str, Enum):
    """Mirrors the `evaluations.status` DB column exactly (docs/architecture/03-db-design.md §14) —
    a pending/running external evaluation is not a new state, just this one reused."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class AgentRunArtifact(BaseModel):
    kind: str
    path: str | None = None
    content: str | None = None


class AgentRunContext(BaseModel):
    """Input to prepare(): the completed agent_run being evaluated."""

    agent_run_id: UUID
    task_id: UUID
    agent_type: str | None = None
    provider: str | None = None
    model_name: str | None = None
    artifacts: list[AgentRunArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluatorInput(BaseModel):
    """Output of prepare(): whatever execute() needs — fixtures, dataset refs, threshold
    config. The phase worth caching/reusing independent of execute() itself."""

    agent_run_id: UUID
    task_id: UUID
    config: dict[str, Any] = Field(default_factory=dict)
    fixtures: dict[str, Any] = Field(default_factory=dict)


class EvaluatorOutputStatus(str, Enum):
    COMPLETED = "completed"
    PENDING_EXTERNAL = "pending_external"


class EvaluatorOutput(BaseModel):
    """Output of execute(). `PENDING_EXTERNAL` is how Braintrust/Langfuse-style evaluators
    signal that scoring happens on the platform's own time, not synchronously
    (docs/architecture/07-evaluation-framework.md §5)."""

    status: EvaluatorOutputStatus = EvaluatorOutputStatus.COMPLETED
    external_ref_id: str | None = None
    raw_result: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)


class MetricScore(BaseModel):
    """One row of `evaluation_results` (docs/architecture/03-db-design.md §15)."""

    metric_name: str
    score: float
    threshold: float | None = None
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    """Output of report(), and the return value of run()/resume_from_external(). The overall
    `status` (passed/failed) is the evaluator author's own judgment — e.g. all-scores-must-pass
    vs. a weighted rule — not something computed generically here. `evaluator_type`,
    `started_at`, and `completed_at` are filled in by run() itself afterward."""

    evaluator_type: EvaluatorType | None = None
    status: EvaluationStatus
    scores: list[MetricScore] = Field(default_factory=list)
    pending_external_ref_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
