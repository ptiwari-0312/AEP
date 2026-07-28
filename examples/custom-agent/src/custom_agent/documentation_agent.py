"""A DocumentationAgent: drafts a documentation update from a task's context via an injected
ModelProvider.

Reference implementation built against sdk/aep-agent-sdk and sdk/aep-provider-sdk, for the
`documentation` agent type (docs/architecture/05-agent-sdk.md §13): input is the task's context
(a code diff and/or existing docs), output is drafted documentation text.
"""

from __future__ import annotations

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
)
from aep_provider_sdk import GenerationRequest, Message, MessageRole, ModelProvider

from .config import DocumentationAgentConfig

_SYSTEM_PROMPT = (
    "You are a documentation-writing assistant. Given the task context (a code diff and/or "
    "existing docs), write a concise, accurate documentation update. Output only the "
    "documentation text."
)


class DocumentationAgent(BaseAgent):
    agent_type = AgentType.DOCUMENTATION

    def __init__(
        self, *, provider: ModelProvider, config: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(config=config, **kwargs)
        self._provider = provider
        self._settings = DocumentationAgentConfig.model_validate(self.config)

    async def plan(self, context: TaskContext) -> Plan:
        # execute() only receives the Plan, not the original TaskContext, so the content it
        # needs to send to the provider has to be carried forward here.
        return Plan(
            steps=[
                PlanStep(
                    description="Draft a documentation update from the task's context",
                    tools=["model_provider.generate"],
                )
            ],
            notes=context.content,
        )

    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        cancellation_token.raise_if_cancelled()
        self.report_progress(percent=10.0, message="requesting documentation draft from provider")

        request = GenerationRequest(
            model=self._settings.model,
            messages=[
                Message(role=MessageRole.SYSTEM, content=_SYSTEM_PROMPT),
                Message(role=MessageRole.USER, content=plan.notes or ""),
            ],
            max_tokens=self._settings.max_tokens,
            temperature=self._settings.temperature,
        )
        response = await self._provider.generate(request)
        cancellation_token.raise_if_cancelled()

        self.report_progress(percent=100.0, message="documentation drafted")
        return ExecutionResult(
            artifacts=[ExecutionArtifact(kind="documentation", content=response.message.content)],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=response.cost_usd or 0.0,
            logs=[f"finish_reason={response.finish_reason.value}"],
        )

    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        content = result.artifacts[0].content if result.artifacts else None
        if not content or len(content.strip()) < self._settings.min_content_length:
            return SelfEvaluation(
                passed=False, confidence=0.9, notes="documentation content is empty or too short"
            )

        if _extract_finish_reason(result.logs) == "max_tokens":
            return SelfEvaluation(
                passed=True, confidence=0.5, notes="output may be truncated (max_tokens reached)"
            )

        return SelfEvaluation(passed=True, confidence=0.9, notes="documentation drafted successfully")

    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        return AgentReport(
            agent_run_status=AgentRunStatus.COMPLETED,
            execution_result=result,
            self_evaluation=self_evaluation,
        )


def _extract_finish_reason(logs: list[str]) -> str | None:
    for line in logs:
        if line.startswith("finish_reason="):
            return line.split("=", 1)[1]
    return None
