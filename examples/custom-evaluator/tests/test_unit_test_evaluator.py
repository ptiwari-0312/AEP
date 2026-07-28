from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from aep_eval_sdk import AgentRunContext, EvaluationStatus
from pydantic import ValidationError

from custom_evaluator import UnitTestEvaluator

FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "sample_project"


def _agent_run(**metadata_overrides: str) -> AgentRunContext:
    metadata: dict[str, str] = {"repo_path": str(FIXTURE_PROJECT)}
    metadata.update(metadata_overrides)
    return AgentRunContext(agent_run_id=uuid4(), task_id=uuid4(), metadata=metadata)


async def test_run_reports_failed_when_a_test_fails() -> None:
    evaluator = UnitTestEvaluator(config={"test_path": "tests"})

    report = await evaluator.run(_agent_run())

    assert report.status == EvaluationStatus.FAILED
    failures_score = next(s for s in report.scores if s.metric_name == "failures")
    assert failures_score.score == 1.0
    assert failures_score.passed is False
    pass_rate_score = next(s for s in report.scores if s.metric_name == "pass_rate")
    assert pass_rate_score.score == 0.5


async def test_run_reports_passed_when_selected_tests_all_pass() -> None:
    evaluator = UnitTestEvaluator(
        config={"test_path": "tests", "pytest_args": ["-k", "test_addition_is_correct"]}
    )

    report = await evaluator.run(_agent_run())

    assert report.status == EvaluationStatus.PASSED
    pass_rate_score = next(s for s in report.scores if s.metric_name == "pass_rate")
    assert pass_rate_score.score == 1.0
    assert pass_rate_score.passed is True


async def test_run_reports_error_when_pytest_produces_no_report() -> None:
    evaluator = UnitTestEvaluator(
        config={"test_path": "tests", "pytest_args": ["--this-flag-does-not-exist"]}
    )

    report = await evaluator.run(_agent_run())

    assert report.status == EvaluationStatus.ERROR
    assert report.error is not None
    assert report.scores == []


async def test_prepare_uses_repo_path_from_agent_run_metadata_over_config_default() -> None:
    evaluator = UnitTestEvaluator(config={"working_directory": "/should/not/be/used"})

    evaluator_input = await evaluator.prepare(_agent_run())

    assert evaluator_input.fixtures["working_directory"] == str(FIXTURE_PROJECT)


def test_invalid_config_raises_at_construction() -> None:
    with pytest.raises(ValidationError):
        UnitTestEvaluator(config={"min_pass_rate": 2.5})
