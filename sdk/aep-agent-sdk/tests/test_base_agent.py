from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from aep_agent_sdk import (
    AgentRunStatus,
    AgentType,
    BaseAgent,
    CancellationToken,
    ExecutionResult,
    Plan,
    RetryableAgentError,
    RetryPolicy,
    SelfEvaluation,
    TaskContext,
    TerminalAgentError,
)
from aep_agent_sdk.types import AgentReport


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))

    def event_types(self) -> list[str]:
        return [event_type for event_type, _ in self.events]


class RecordingMetricsSink:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict[str, Any]]] = []

    def emit(self, metric_name: str, value: float, **tags: Any) -> None:
        self.metrics.append((metric_name, value, tags))


class HappyPathAgent(BaseAgent):
    agent_type = AgentType.CODING

    async def plan(self, context: TaskContext) -> Plan:
        return Plan(steps=[])

    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        return ExecutionResult(input_tokens=10, output_tokens=20, cost_usd=0.01)

    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        return SelfEvaluation(passed=True, confidence=0.9, notes="looks fine")

    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        return AgentReport(agent_run_status=AgentRunStatus.COMPLETED, execution_result=result, self_evaluation=self_evaluation)


class FlakyThenSucceedsAgent(BaseAgent):
    agent_type = AgentType.CODING

    def __init__(self, *, failures_before_success: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._remaining_failures = failures_before_success

    async def plan(self, context: TaskContext) -> Plan:
        return Plan(steps=[])

    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RetryableAgentError("transient provider timeout")
        return ExecutionResult()

    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        return SelfEvaluation(passed=True, confidence=1.0)

    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        return AgentReport(agent_run_status=AgentRunStatus.COMPLETED, execution_result=result, self_evaluation=self_evaluation)


class AlwaysTerminalAgent(BaseAgent):
    agent_type = AgentType.CODING

    async def plan(self, context: TaskContext) -> Plan:
        raise TerminalAgentError("bad config")

    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        raise AssertionError("should never reach execute()")

    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        raise AssertionError("should never reach evaluate()")

    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        raise AssertionError("should never reach report()")


class CancellingAgent(BaseAgent):
    agent_type = AgentType.CODING

    async def plan(self, context: TaskContext) -> Plan:
        return Plan(steps=[])

    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        await self.cancel()
        cancellation_token.raise_if_cancelled()
        raise AssertionError("unreachable")

    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        raise AssertionError("should never reach evaluate()")

    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        raise AssertionError("should never reach report()")


class ProgressReportingAgent(BaseAgent):
    agent_type = AgentType.TESTING

    async def plan(self, context: TaskContext) -> Plan:
        return Plan(steps=[])

    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        self.report_progress(percent=42.0, message="halfway there")
        return ExecutionResult()

    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        return SelfEvaluation(passed=True, confidence=1.0)

    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        return AgentReport(agent_run_status=AgentRunStatus.COMPLETED)


def _context() -> TaskContext:
    return TaskContext(task_id=uuid4(), content="do the thing")


async def test_happy_path_returns_completed_and_publishes_full_event_sequence() -> None:
    publisher = RecordingEventPublisher()
    metrics = RecordingMetricsSink()
    agent = HappyPathAgent(
        agent_id=uuid4(), version="0.1.0", event_publisher=publisher, metrics_sink=metrics
    )

    report = await agent.run(_context())

    assert report.agent_run_status == AgentRunStatus.COMPLETED
    assert report.attempt_number == 1
    assert report.execution_result is not None
    assert report.execution_result.cost_usd == 0.01
    assert report.self_evaluation is not None
    assert report.self_evaluation.passed is True
    assert publisher.event_types() == [
        "agent_run.queued",
        "agent_run.planning",
        "agent_run.executing",
        "agent_run.self_evaluating",
        "agent_run.reporting",
        "agent_run.completed",
    ]
    metric_names = {name for name, _, _ in metrics.metrics}
    assert "agent_run.duration_ms" in metric_names
    assert "agent_run.cost_usd" in metric_names
    assert "agent_run.self_eval_passed" in metric_names


async def test_retryable_error_retries_then_succeeds() -> None:
    publisher = RecordingEventPublisher()
    agent = FlakyThenSucceedsAgent(
        agent_id=uuid4(),
        version="0.1.0",
        failures_before_success=2,
        event_publisher=publisher,
        retry_policy=RetryPolicy(max_attempts=5, backoff_base_seconds=0.01, backoff_multiplier=1.0),
    )

    report = await agent.run(_context())

    assert report.agent_run_status == AgentRunStatus.COMPLETED
    assert report.attempt_number == 3
    assert publisher.event_types().count("agent_run.retrying") == 2
    assert publisher.event_types().count("agent_run.queued") == 1


async def test_retryable_error_fails_after_max_attempts() -> None:
    agent = FlakyThenSucceedsAgent(
        agent_id=uuid4(),
        version="0.1.0",
        failures_before_success=10,
        retry_policy=RetryPolicy(max_attempts=3, backoff_base_seconds=0.01, backoff_multiplier=1.0),
    )

    report = await agent.run(_context())

    assert report.agent_run_status == AgentRunStatus.FAILED
    assert report.attempt_number == 3
    assert report.error is not None


async def test_terminal_error_fails_immediately_without_retry() -> None:
    publisher = RecordingEventPublisher()
    agent = AlwaysTerminalAgent(
        agent_id=uuid4(),
        version="0.1.0",
        event_publisher=publisher,
        retry_policy=RetryPolicy(max_attempts=5, backoff_base_seconds=0.01),
    )

    report = await agent.run(_context())

    assert report.agent_run_status == AgentRunStatus.FAILED
    assert report.attempt_number == 1
    assert "agent_run.retrying" not in publisher.event_types()


async def test_cancellation_produces_cancelled_report_not_a_retry() -> None:
    publisher = RecordingEventPublisher()
    agent = CancellingAgent(agent_id=uuid4(), version="0.1.0", event_publisher=publisher)

    report = await agent.run(_context())

    assert report.agent_run_status == AgentRunStatus.CANCELLED
    assert "agent_run.cancelled" in publisher.event_types()
    assert "agent_run.retrying" not in publisher.event_types()
    assert "agent_run.failed" not in publisher.event_types()


async def test_report_progress_updates_heartbeat_signal() -> None:
    agent = ProgressReportingAgent(agent_id=uuid4(), version="0.1.0")

    await agent.run(_context())

    signal = agent.heartbeat()
    assert signal.progress_percent == 42.0
    assert signal.message == "halfway there"


def test_subclass_cannot_override_final_lifecycle_methods() -> None:
    with pytest.raises(TypeError, match="run"):

        class BadAgent(BaseAgent):
            agent_type = AgentType.CODING

            async def plan(self, context: TaskContext) -> Plan:
                return Plan(steps=[])

            async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
                return ExecutionResult()

            async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
                return SelfEvaluation(passed=True, confidence=1.0)

            async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
                return AgentReport(agent_run_status=AgentRunStatus.COMPLETED)

            async def run(self, context: TaskContext, *, agent_run_id: UUID | None = None) -> AgentReport:  # type: ignore[override]
                raise AssertionError("must never be called")


def test_agent_without_agent_type_raises_at_construction() -> None:
    class NoTypeAgent(BaseAgent):
        async def plan(self, context: TaskContext) -> Plan:
            return Plan(steps=[])

        async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
            return ExecutionResult()

        async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
            return SelfEvaluation(passed=True, confidence=1.0)

        async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
            return AgentReport(agent_run_status=AgentRunStatus.COMPLETED)

    with pytest.raises(TypeError, match="agent_type"):
        NoTypeAgent(agent_id=uuid4(), version="0.1.0")
