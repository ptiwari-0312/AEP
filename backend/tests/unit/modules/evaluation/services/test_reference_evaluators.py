from __future__ import annotations

from uuid import uuid4

import pytest
from aep_eval_sdk import AgentRunContext, EvaluationStatus
from pydantic import ValidationError

from aep.modules.evaluation.services.reference_evaluators import (
    EchoJudgeEvaluator,
    PerformanceEvaluator,
    UnitTestEvaluator,
)


def _context(**metadata) -> AgentRunContext:
    return AgentRunContext(agent_run_id=uuid4(), task_id=uuid4(), metadata=metadata)


async def test_performance_evaluator_passes_within_thresholds() -> None:
    evaluator = PerformanceEvaluator(config={"max_cost_usd": 1.0, "max_duration_seconds": 30.0})
    context = _context(cost_usd=0.5, duration_seconds=10.0)

    report = await evaluator.run(context)

    assert report.status == EvaluationStatus.PASSED
    assert {s.metric_name for s in report.scores} == {"cost_usd", "duration_seconds"}
    assert all(s.passed for s in report.scores)


async def test_performance_evaluator_fails_when_cost_exceeds_threshold() -> None:
    evaluator = PerformanceEvaluator(config={"max_cost_usd": 0.10})
    context = _context(cost_usd=5.0, duration_seconds=1.0)

    report = await evaluator.run(context)

    assert report.status == EvaluationStatus.FAILED
    cost_score = next(s for s in report.scores if s.metric_name == "cost_usd")
    assert cost_score.passed is False


async def test_performance_evaluator_passes_with_no_thresholds_configured() -> None:
    evaluator = PerformanceEvaluator()
    context = _context(cost_usd=1000.0)

    report = await evaluator.run(context)

    assert report.status == EvaluationStatus.PASSED
    assert report.scores[0].metric_name == "no_thresholds_configured"


async def test_echo_judge_evaluator_reports_configured_verdict() -> None:
    passing = EchoJudgeEvaluator(config={"passed": True})
    failing = EchoJudgeEvaluator(config={"passed": False})
    context = _context()

    passing_report = await passing.run(context)
    failing_report = await failing.run(context)

    assert passing_report.status == EvaluationStatus.PASSED
    assert failing_report.status == EvaluationStatus.FAILED


async def test_unit_test_evaluator_runs_real_pytest_against_a_real_directory(tmp_path) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_pass():\n    assert True\n\n\ndef test_fail():\n    assert False\n"
    )
    evaluator = UnitTestEvaluator(config={"working_directory": str(tmp_path), "min_pass_rate": 1.0})
    context = _context()

    report = await evaluator.run(context)

    assert report.status == EvaluationStatus.FAILED
    pass_rate_score = next(s for s in report.scores if s.metric_name == "pass_rate")
    assert pass_rate_score.details == {"total": 2, "passed": 1, "failed": 1}


async def test_unit_test_evaluator_passes_when_all_tests_pass(tmp_path) -> None:
    (tmp_path / "test_sample.py").write_text("def test_pass():\n    assert True\n")
    evaluator = UnitTestEvaluator(config={"working_directory": str(tmp_path)})
    context = _context()

    report = await evaluator.run(context)

    assert report.status == EvaluationStatus.PASSED


async def test_unit_test_evaluator_requires_working_directory_config() -> None:
    with pytest.raises(ValidationError):
        UnitTestEvaluator(config={})
