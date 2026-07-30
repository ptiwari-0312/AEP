"""A minimal, dependency-free `BaseAgent` implementation used as this module's registered
runtime agent when no real provider-backed agent is configured.

No `ModelProvider` credentials (e.g. a paid Anthropic API key) are wired into `backend/` — see
`context_builder`'s identical stance. Rather than skip real execution entirely, `EchoAgent` lets
the orchestration pipeline itself (assign -> start run -> `BaseAgent.run()` -> heartbeat ->
cooperative cancellation -> event publishing -> persistence -> task-status transition) be
exercised genuinely end-to-end: it's a real, working `BaseAgent` subclass — real inheritance, real
`plan`/`execute`/`evaluate`/`report` hooks, real cooperative cancellation — it just doesn't call
an external LLM. A real deployment would register `DocumentationAgent`
(`examples/custom-agent`)-style instances backed by a real `ModelProvider` instead.

This class deliberately has **no** class-level `agent_type` — `BaseAgent.agent_type` is a
`ClassVar[AgentType]`, and normally one concrete `BaseAgent` subclass maps to exactly one agent
type (e.g. `DocumentationAgent.agent_type = AgentType.DOCUMENTATION`). Since one `EchoAgent`
needs to stand in for whichever of the eight types a given `agents` catalog row declares,
`make_echo_agent_class()` below creates one small dynamic subclass per `AgentType`, each setting
`agent_type` as a genuine class attribute — not an instance assigning over a `ClassVar` (mypy
correctly flags that as illegal, and it was the first draft's approach before this one).
`AgentRegistry` calls `make_echo_agent_class()` once per type rather than instantiating
`EchoAgent` directly.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aep_agent_sdk import (
    AgentReport,
    AgentRunStatus,
    AgentType,
    BaseAgent,
    CancellationToken,
    ExecutionArtifact,
    ExecutionResult,
    Plan,
    PlanStep,
    SelfEvaluation,
    TaskContext,
    TerminalAgentError,
)
from pydantic import BaseModel, Field


class EchoAgentConfig(BaseModel):
    """Parsed from an `agents.config` JSON blob (docs/architecture/03-db-design.md §8)."""

    execution_delay_seconds: float = Field(default=0.0, ge=0.0)
    fail: bool = False
    poll_interval_seconds: float = Field(default=0.02, gt=0.0)


class EchoAgent(BaseAgent):
    def __init__(self, *, config: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(config=config, **kwargs)
        self._settings = EchoAgentConfig.model_validate(self.config)

    async def plan(self, context: TaskContext) -> Plan:
        # execute() only receives the Plan, not the original TaskContext, so the content it
        # needs has to be carried forward here — same pattern as
        # examples/custom-agent's DocumentationAgent.
        return Plan(
            steps=[PlanStep(description="Echo the task's assembled context back as an artifact")],
            notes=context.content,
        )

    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        elapsed = 0.0
        delay = self._settings.execution_delay_seconds
        step = self._settings.poll_interval_seconds
        while elapsed < delay:
            cancellation_token.raise_if_cancelled()
            await asyncio.sleep(min(step, delay - elapsed))
            elapsed += step
            self.report_progress(percent=min(99.0, elapsed / delay * 100.0))
        cancellation_token.raise_if_cancelled()

        if self._settings.fail:
            raise TerminalAgentError("EchoAgent is configured to fail (config.fail=true)")

        content = plan.notes or ""
        self.report_progress(percent=100.0, message="echoed")
        return ExecutionResult(
            artifacts=[ExecutionArtifact(kind="echo", content=content)],
            input_tokens=max(1, len(content) // 4),
            output_tokens=max(1, len(content) // 4),
            cost_usd=0.0,
            logs=["echo executed"],
        )

    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        return SelfEvaluation(passed=True, confidence=1.0, notes="EchoAgent always self-passes")

    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        return AgentReport(
            agent_run_status=AgentRunStatus.COMPLETED,
            execution_result=result,
            self_evaluation=self_evaluation,
        )


def make_echo_agent_class(agent_type: AgentType) -> type[EchoAgent]:
    """One small dynamic subclass per `AgentType`, each with `agent_type` set as a real class
    attribute — see this module's docstring for why `EchoAgent` itself doesn't declare one."""
    return type(f"EchoAgent_{agent_type.value}", (EchoAgent,), {"agent_type": agent_type})
