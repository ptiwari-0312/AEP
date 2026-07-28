"""Data types exchanged across the BaseAgent lifecycle (docs/architecture/05-agent-sdk.md §2.1)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    """The eight agent types from docs/architecture/05-agent-sdk.md §13."""

    PLANNER = "planner"
    ARCHITECT = "architect"
    CODING = "coding"
    TESTING = "testing"
    REVIEW = "review"
    DOCUMENTATION = "documentation"
    SECURITY = "security"
    EVALUATION = "evaluation"


class AgentRunStatus(str, Enum):
    """Fine-grained SDK-level lifecycle states (docs/architecture/05-agent-sdk.md §3) — deliberately
    finer than the `agent_runs.status` DB column, which only needs queued/running/succeeded/
    failed/cancelled/retrying."""

    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    SELF_EVALUATING = "self_evaluating"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class TaskContext(BaseModel):
    """Input to plan()/execute(): the task and its Context Package
    (docs/architecture/06-context-builder.md)."""

    task_id: UUID
    context_package_id: UUID | None = None
    content: str
    prompt_template_id: UUID | None = None
    prompt_version_number: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    """One step of a Plan: what the agent intends to do and with what."""

    description: str
    tools: list[str] = Field(default_factory=list)
    estimated_cost_usd: float | None = None


class Plan(BaseModel):
    """Output of plan(): an ordered list of steps the agent intends to execute."""

    steps: list[PlanStep] = Field(default_factory=list)
    notes: str | None = None


class ExecutionArtifact(BaseModel):
    """One artifact produced by execute() — a diff, a generated file, a log, a doc update."""

    kind: str
    path: str | None = None
    content: str | None = None


class ExecutionResult(BaseModel):
    """Output of execute(): artifacts produced plus token/cost accounting."""

    artifacts: list[ExecutionArtifact] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    logs: list[str] = Field(default_factory=list)


class SelfEvaluation(BaseModel):
    """Output of evaluate(): the agent's own cheap, immediate self-check — not the authoritative
    quality gate (docs/architecture/05-agent-sdk.md §14)."""

    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    notes: str = ""


class AgentReport(BaseModel):
    """Output of report(), and the return value of run()/retry(). `agent_run_status`,
    `attempt_number`, `started_at`, and `completed_at` are filled in by run() itself after
    report() returns — a hook author doesn't need to set them."""

    agent_run_status: AgentRunStatus
    execution_result: ExecutionResult | None = None
    self_evaluation: SelfEvaluation | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempt_number: int = 1
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.started_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds() * 1000


class HeartbeatSignal(BaseModel):
    """Returned by heartbeat(); also what the background heartbeat loop publishes on interval
    (docs/architecture/05-agent-sdk.md §8)."""

    timestamp: datetime
    progress_percent: float | None = None
    message: str | None = None
