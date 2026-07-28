from __future__ import annotations

from uuid import uuid4

from aep.modules.task_memory.domain.models import (
    Task,
    TaskStatus,
    TaskType,
    is_legal_task_transition,
    requires_dependencies_satisfied,
)


def test_task_defaults_to_pending_status() -> None:
    task = Task(id=uuid4(), feature_id=uuid4(), title="Add endpoint", task_type=TaskType.CODE)

    assert task.status == TaskStatus.PENDING
    assert task.priority == 0
    assert task.assigned_agent_id is None


def test_legal_transitions_from_pending() -> None:
    assert is_legal_task_transition(TaskStatus.PENDING, TaskStatus.READY)
    assert is_legal_task_transition(TaskStatus.PENDING, TaskStatus.BLOCKED)
    assert is_legal_task_transition(TaskStatus.PENDING, TaskStatus.CANCELLED)
    assert not is_legal_task_transition(TaskStatus.PENDING, TaskStatus.RUNNING)


def test_approve_and_merge_gate_matches_orchestrator_preconditions() -> None:
    # docs/architecture/04-api-design.md §5: approve requires awaiting_approval, merge requires approved.
    assert is_legal_task_transition(TaskStatus.AWAITING_APPROVAL, TaskStatus.APPROVED)
    assert not is_legal_task_transition(TaskStatus.AWAITING_APPROVAL, TaskStatus.MERGED)
    assert is_legal_task_transition(TaskStatus.APPROVED, TaskStatus.MERGED)
    assert not is_legal_task_transition(TaskStatus.EVALUATING, TaskStatus.APPROVED)


def test_failed_and_rejected_can_be_retried_via_ready() -> None:
    assert is_legal_task_transition(TaskStatus.FAILED, TaskStatus.READY)
    assert is_legal_task_transition(TaskStatus.REJECTED, TaskStatus.READY)


def test_terminal_statuses_have_no_legal_outgoing_transitions() -> None:
    for target in TaskStatus:
        assert not is_legal_task_transition(TaskStatus.MERGED, target)
        assert not is_legal_task_transition(TaskStatus.CANCELLED, target)


def test_dependency_gated_statuses_are_running_only() -> None:
    assert requires_dependencies_satisfied(TaskStatus.RUNNING)
    assert not requires_dependencies_satisfied(TaskStatus.READY)
    assert not requires_dependencies_satisfied(TaskStatus.PENDING)
    assert not requires_dependencies_satisfied(TaskStatus.MERGED)
