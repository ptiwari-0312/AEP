"""Domain-level errors for the Evaluation Framework — pure Python, no framework imports, and no
dependency on `core/errors.py`'s HTTP-mapped `AEPError` hierarchy either: the `api/` layer is the
sole translation boundary between these and an HTTP response
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID

from .models import EvaluatorType


class EvaluationDomainError(Exception):
    """Base class for every Evaluation Framework domain error."""


class EvaluationNotFoundError(EvaluationDomainError):
    def __init__(self, evaluation_id: UUID) -> None:
        super().__init__(f"evaluation {evaluation_id} not found")
        self.evaluation_id = evaluation_id


class AgentRunNotFoundError(EvaluationDomainError):
    """This module's local equivalent of `orchestrator.domain.errors.AgentRunNotFoundError`."""

    def __init__(self, agent_run_id: UUID) -> None:
        super().__init__(f"agent run {agent_run_id} not found")
        self.agent_run_id = agent_run_id


class TaskNotFoundError(EvaluationDomainError):
    """This module's local equivalent of `orchestrator.domain.errors.TaskNotFoundError` (itself
    `orchestrator`'s local equivalent of `task_memory`'s) — this module never talks to
    `task_memory` directly, only to `orchestrator`'s public `AgentRunService`, so it translates
    from *that* module's exception, not `task_memory`'s."""

    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"task {task_id} not found")
        self.task_id = task_id


class AgentRunNotSucceededError(EvaluationDomainError):
    def __init__(self, agent_run_id: UUID) -> None:
        super().__init__(f"agent run {agent_run_id} has not succeeded yet")
        self.agent_run_id = agent_run_id


class EvaluatorTypeNotRegisteredError(EvaluationDomainError):
    def __init__(self, evaluator_type: EvaluatorType) -> None:
        super().__init__(f"no evaluator plugin is registered for {evaluator_type.value!r}")
        self.evaluator_type = evaluator_type
