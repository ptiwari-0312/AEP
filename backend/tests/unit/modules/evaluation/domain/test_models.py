from __future__ import annotations

from uuid import uuid4

from aep.modules.evaluation.domain.models import (
    Evaluation,
    EvaluationResult,
    EvaluationStatus,
    EvaluatorType,
    QualityGateResult,
)


def test_evaluation_defaults() -> None:
    evaluation = Evaluation(
        id=uuid4(), agent_run_id=uuid4(), evaluator_type=EvaluatorType.UNIT_TEST
    )

    assert evaluation.status == EvaluationStatus.PENDING
    assert evaluation.started_at is None


def test_evaluation_result_defaults() -> None:
    result = EvaluationResult(
        id=uuid4(), evaluation_id=uuid4(), metric_name="pass_rate", score=1.0, passed=True
    )

    assert result.threshold is None
    assert result.details == {}


def test_quality_gate_result_pending_state() -> None:
    gate = QualityGateResult(task_id=uuid4(), agent_run_id=None, overall="pending", evaluations=[])

    assert gate.agent_run_id is None
    assert gate.evaluations == []


def test_evaluator_type_matches_db_check_constraint_values() -> None:
    # docs/architecture/03-db-design.md §14's CHECK IN (...) list, verbatim.
    expected = {
        "deepeval",
        "promptfoo",
        "llm_judge",
        "braintrust",
        "langfuse",
        "unit_test",
        "integration_test",
        "security_scan",
        "static_analysis",
        "coverage",
        "performance",
        "architecture_rules",
    }
    assert {member.value for member in EvaluatorType} == expected


def test_evaluation_status_matches_db_check_constraint_values() -> None:
    expected = {"pending", "running", "passed", "failed", "error"}
    assert {member.value for member in EvaluationStatus} == expected
