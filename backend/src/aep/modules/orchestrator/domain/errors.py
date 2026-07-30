"""Domain-level errors for the Agent Orchestrator — pure Python, no framework imports, and no
dependency on `core/errors.py`'s HTTP-mapped `AEPError` hierarchy either: the `api/` layer is the
sole translation boundary between these and an HTTP response
(docs/architecture/09-engineering-standards.md §6).
"""

from __future__ import annotations

from uuid import UUID


class AgentOrchestratorDomainError(Exception):
    """Base class for every Agent Orchestrator domain error."""


class AgentNotFoundError(AgentOrchestratorDomainError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"agent {agent_id} not found")
        self.agent_id = agent_id


class AgentNameVersionExistsError(AgentOrchestratorDomainError):
    def __init__(self, name: str, version: str) -> None:
        super().__init__(f"an agent named {name!r} at version {version!r} already exists")
        self.name = name
        self.version = version


class AgentDisabledError(AgentOrchestratorDomainError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"agent {agent_id} is disabled")
        self.agent_id = agent_id


class AgentRunNotFoundError(AgentOrchestratorDomainError):
    def __init__(self, agent_run_id: UUID) -> None:
        super().__init__(f"agent run {agent_run_id} not found")
        self.agent_run_id = agent_run_id


class TaskNotFoundError(AgentOrchestratorDomainError):
    """This module's local equivalent of `task_memory.domain.errors.TaskNotFoundError` —
    translated at the `services/` boundary, the same pattern `task_memory` uses for the Project
    Service's `FeatureNotFoundError` (see that module's README)."""

    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"task {task_id} not found")
        self.task_id = task_id


class ContextPackageNotFoundError(AgentOrchestratorDomainError):
    """This module's local equivalent of `context_builder.domain.errors.ContextPackageNotFoundError`,
    also raised when a context package exists but belongs to a different task than the one a run
    was requested for."""

    def __init__(self, context_package_id: UUID) -> None:
        super().__init__(f"context package {context_package_id} not found for this task")
        self.context_package_id = context_package_id


class TaskHasNoAssignedAgentError(AgentOrchestratorDomainError):
    def __init__(self, task_id: UUID) -> None:
        super().__init__(f"task {task_id} has no assigned agent")
        self.task_id = task_id


class TaskTransitionNotAllowedError(AgentOrchestratorDomainError):
    """Raised whenever `task_memory`'s own state machine rejects a transition this module tried
    to drive (illegal transition or unmet dependencies) — translated into this module's local
    equivalent rather than leaking `task_memory`'s exception type across the boundary."""

    def __init__(self, task_id: UUID, detail: str) -> None:
        super().__init__(f"task {task_id}: {detail}")
        self.task_id = task_id


class AgentRunNotCancellableError(AgentOrchestratorDomainError):
    def __init__(self, agent_run_id: UUID) -> None:
        super().__init__(f"agent run {agent_run_id} is not cancellable (not queued or running)")
        self.agent_run_id = agent_run_id


class AgentRunNotRetryableError(AgentOrchestratorDomainError):
    def __init__(self, agent_run_id: UUID) -> None:
        super().__init__(f"agent run {agent_run_id} is not retryable (not failed)")
        self.agent_run_id = agent_run_id
