"""Pure domain entities and value objects for the Task Memory Service
(docs/architecture/03-db-design.md §6-7, §19; docs/architecture/02-repo-design.md §2's domain/
layer — zero framework imports).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class TaskType(str, Enum):
    PLAN = "plan"
    ARCHITECT = "architect"
    CODE = "code"
    TEST = "test"
    REVIEW = "review"
    DOCUMENT = "document"
    SECURITY = "security"
    EVALUATE = "evaluate"


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    EVALUATING = "evaluating"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED = "merged"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DependencyType(str, Enum):
    BLOCKS = "blocks"
    INFORMS = "informs"


# The pipeline from docs/architecture/01-vision-and-principles.md §5 (Generate Task Graph ->
# Assign Agent -> Generate Context -> Generate Code -> Run Evaluations -> Human Approval ->
# Merge), expressed as a state machine. Neither doc explicitly enumerates every edge; this is
# the reasonable graph implied by that pipeline plus the Orchestrator's approve/merge
# preconditions (docs/architecture/04-api-design.md §5: approve requires `awaiting_approval`,
# merge requires `approved`). MERGED and CANCELLED are terminal.
_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset({TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.EVALUATING, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.EVALUATING: frozenset(
        {TaskStatus.AWAITING_APPROVAL, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.AWAITING_APPROVAL: frozenset({TaskStatus.APPROVED, TaskStatus.REJECTED}),
    TaskStatus.APPROVED: frozenset({TaskStatus.MERGED}),
    TaskStatus.REJECTED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.FAILED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.MERGED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

# docs/architecture/04-api-design.md §3: "409 (illegal transition or unmet dependencies — e.g.
# moving to running while a depends_on task is not merged)" — the doc's own example gates only
# RUNNING, not READY: READY means "queued, eligible in principle" (a task graph should be able
# to show a task as ready even before its blocker finishes); RUNNING means "actually starting
# execution," which is where unmet dependencies must hard-block.
_DEPENDENCY_GATED_STATUSES = frozenset({TaskStatus.RUNNING})


def is_legal_task_transition(current: TaskStatus, target: TaskStatus) -> bool:
    return target in _TASK_TRANSITIONS[current]


def requires_dependencies_satisfied(target: TaskStatus) -> bool:
    return target in _DEPENDENCY_GATED_STATUSES


@dataclass
class Task:
    id: UUID
    feature_id: UUID
    title: str
    task_type: TaskType
    description: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent_id: UUID | None = None
    priority: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class TaskDependency:
    id: UUID
    task_id: UUID
    depends_on_task_id: UUID
    dependency_type: DependencyType = DependencyType.BLOCKS
    created_at: datetime | None = None


@dataclass
class ExecutionHistoryEntry:
    id: UUID
    task_id: UUID
    to_status: TaskStatus
    from_status: TaskStatus | None = None
    changed_by_user_id: UUID | None = None
    changed_by_agent_id: UUID | None = None
    reason: str | None = None
    created_at: datetime | None = None
