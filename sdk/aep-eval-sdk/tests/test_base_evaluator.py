from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from aep_eval_sdk import (
    AgentRunContext,
    BaseEvaluator,
    EvaluationReport,
    EvaluationStatus,
    EvaluatorInput,
    EvaluatorOutput,
    EvaluatorOutputStatus,
    EvaluatorType,
    MetricScore,
)


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


class HappyPathEvaluator(BaseEvaluator):
    evaluator_type = EvaluatorType.UNIT_TEST

    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        return EvaluatorInput(agent_run_id=agent_run.agent_run_id, task_id=agent_run.task_id)

    async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
        return EvaluatorOutput(raw_result={"tests_passed": 10, "tests_failed": 0})

    async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
        return [MetricScore(metric_name="pass_rate", score=1.0, threshold=0.9, passed=True)]

    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        all_passed = all(s.passed for s in scores)
        return EvaluationReport(
            status=EvaluationStatus.PASSED if all_passed else EvaluationStatus.FAILED,
            scores=scores,
        )


class PendingExternalEvaluator(BaseEvaluator):
    evaluator_type = EvaluatorType.BRAINTRUST

    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        return EvaluatorInput(agent_run_id=agent_run.agent_run_id, task_id=agent_run.task_id)

    async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
        return EvaluatorOutput(
            status=EvaluatorOutputStatus.PENDING_EXTERNAL, external_ref_id="braintrust-run-123"
        )

    async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
        raw = output.raw_result
        return [MetricScore(metric_name="faithfulness", score=raw["faithfulness"], passed=raw["faithfulness"] >= 0.8)]

    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        all_passed = all(s.passed for s in scores)
        return EvaluationReport(
            status=EvaluationStatus.PASSED if all_passed else EvaluationStatus.FAILED,
            scores=scores,
        )


class FailingEvaluator(BaseEvaluator):
    evaluator_type = EvaluatorType.STATIC_ANALYSIS

    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        return EvaluatorInput(agent_run_id=agent_run.agent_run_id, task_id=agent_run.task_id)

    async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
        raise RuntimeError("linter crashed")

    async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
        raise AssertionError("should never reach score()")

    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        raise AssertionError("should never reach report()")


def _agent_run() -> AgentRunContext:
    return AgentRunContext(agent_run_id=uuid4(), task_id=uuid4())


async def test_happy_path_returns_passed_and_publishes_full_event_sequence() -> None:
    publisher = RecordingEventPublisher()
    metrics = RecordingMetricsSink()
    evaluator = HappyPathEvaluator(event_publisher=publisher, metrics_sink=metrics)

    report = await evaluator.run(_agent_run())

    assert report.status == EvaluationStatus.PASSED
    assert report.evaluator_type == EvaluatorType.UNIT_TEST
    assert len(report.scores) == 1
    assert report.scores[0].passed is True
    assert publisher.event_types() == [
        "evaluation.preparing",
        "evaluation.executing",
        "evaluation.scoring",
        "evaluation.reporting",
        "evaluation.completed",
    ]
    metric_names = {name for name, _, _ in metrics.metrics}
    assert "evaluation.duration_ms" in metric_names
    assert "evaluation.passed" in metric_names
    assert "evaluation.score.pass_rate" in metric_names


async def test_pending_external_defers_scoring_until_resume() -> None:
    publisher = RecordingEventPublisher()
    evaluator = PendingExternalEvaluator(event_publisher=publisher)
    agent_run = _agent_run()

    report = await evaluator.run(agent_run)

    assert report.status == EvaluationStatus.RUNNING
    assert report.pending_external_ref_id == "braintrust-run-123"
    assert report.scores == []
    assert "evaluation.pending_external" in publisher.event_types()
    assert "evaluation.scoring" not in publisher.event_types()

    resumed_output = EvaluatorOutput(
        status=EvaluatorOutputStatus.COMPLETED, raw_result={"faithfulness": 0.95}
    )
    final_report = await evaluator.resume_from_external(agent_run, resumed_output)

    assert final_report.status == EvaluationStatus.PASSED
    assert final_report.scores[0].metric_name == "faithfulness"
    assert "evaluation.completed" in publisher.event_types()


async def test_resume_from_external_rejects_non_completed_output() -> None:
    evaluator = PendingExternalEvaluator()
    agent_run = _agent_run()
    still_pending = EvaluatorOutput(status=EvaluatorOutputStatus.PENDING_EXTERNAL)

    with pytest.raises(ValueError, match="COMPLETED"):
        await evaluator.resume_from_external(agent_run, still_pending)


async def test_execute_error_produces_error_report_not_a_raised_exception() -> None:
    publisher = RecordingEventPublisher()
    evaluator = FailingEvaluator(event_publisher=publisher)

    report = await evaluator.run(_agent_run())

    assert report.status == EvaluationStatus.ERROR
    assert report.error == "linter crashed"
    assert "evaluation.error" in publisher.event_types()
    assert "evaluation.completed" not in publisher.event_types()


def test_subclass_cannot_override_final_lifecycle_methods() -> None:
    with pytest.raises(TypeError, match="run"):

        class BadEvaluator(BaseEvaluator):
            evaluator_type = EvaluatorType.UNIT_TEST

            async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
                return EvaluatorInput(agent_run_id=agent_run.agent_run_id, task_id=agent_run.task_id)

            async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
                return EvaluatorOutput()

            async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
                return []

            async def report(self, scores: list[MetricScore]) -> EvaluationReport:
                return EvaluationReport(status=EvaluationStatus.PASSED)

            async def run(self, agent_run: AgentRunContext) -> EvaluationReport:  # type: ignore[override]
                raise AssertionError("must never be called")


def test_evaluator_without_evaluator_type_raises_at_construction() -> None:
    class NoTypeEvaluator(BaseEvaluator):
        async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
            return EvaluatorInput(agent_run_id=agent_run.agent_run_id, task_id=agent_run.task_id)

        async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
            return EvaluatorOutput()

        async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
            return []

        async def report(self, scores: list[MetricScore]) -> EvaluationReport:
            return EvaluationReport(status=EvaluationStatus.PASSED)

    with pytest.raises(TypeError, match="evaluator_type"):
        NoTypeEvaluator()
