from __future__ import annotations

from uuid import uuid4

from aep.modules.orchestrator.domain.models import (
    Agent,
    AgentRun,
    AgentRunStatus,
    AgentType,
    TaskSummary,
)


def test_agent_defaults() -> None:
    agent = Agent(id=uuid4(), name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")

    assert agent.is_enabled is True
    assert agent.config == {}


def test_agent_run_defaults() -> None:
    run = AgentRun(
        id=uuid4(), agent_id=uuid4(), task_id=uuid4(), provider="claude", model_name="claude-x"
    )

    assert run.status == AgentRunStatus.QUEUED
    assert run.attempt_number == 1
    assert run.context_package_id is None


def test_agent_run_status_matches_db_check_constraint_values() -> None:
    # docs/architecture/03-db-design.md §9's CHECK IN (...) list, verbatim.
    expected = {"queued", "running", "succeeded", "failed", "cancelled", "retrying"}
    assert {member.value for member in AgentRunStatus} == expected


def test_agent_type_matches_sdk_and_db_check_constraint_values() -> None:
    # docs/architecture/03-db-design.md §8's CHECK IN (...) list must match aep_agent_sdk's own
    # AgentType exactly, since this module imports it rather than redefining it.
    expected = {
        "planner",
        "architect",
        "coding",
        "testing",
        "review",
        "documentation",
        "security",
        "evaluation",
    }
    assert {member.value for member in AgentType} == expected


def test_task_summary_is_a_local_projection() -> None:
    summary = TaskSummary(id=uuid4(), status="running")

    assert summary.assigned_agent_id is None
    assert summary.updated_at is None
