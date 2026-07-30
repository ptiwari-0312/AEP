"""Pure domain entities and value objects for the Agent Orchestrator
(docs/architecture/03-db-design.md §8-9; docs/architecture/05-agent-sdk.md;
docs/architecture/02-repo-design.md §2's domain/ layer — zero framework imports).

`AgentType` is imported from `aep_agent_sdk` rather than redefined here — the eight agent types
are the SDK's own contract (`BaseAgent.agent_type`), and this module's `agents` catalog exists to
register instances of that same enum, not a parallel one that could drift out of sync with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from aep_agent_sdk import AgentType

__all__ = [
    "Agent",
    "AgentRun",
    "AgentRunStatus",
    "AgentType",
    "TaskSummary",
]


class AgentRunStatus(str, Enum):
    """The DB-level `agent_runs.status` column (docs/architecture/03-db-design.md §9) —
    deliberately coarser than the SDK's own `aep_agent_sdk.AgentRunStatus`, which additionally
    tracks in-flight sub-states (`planning`, `executing`, ...) that only matter while a run is
    live, not once persisted."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class Agent:
    id: UUID
    name: str
    agent_type: AgentType
    version: str
    is_enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class AgentRun:
    id: UUID
    agent_id: UUID
    task_id: UUID
    provider: str
    model_name: str
    context_package_id: UUID | None = None
    status: AgentRunStatus = AgentRunStatus.QUEUED
    attempt_number: int = 1
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    error_message: str | None = None
    created_at: datetime | None = None


@dataclass
class TaskSummary:
    """A local projection of `task_memory`'s `Task`, not a re-export of it — this module's public
    methods return their own domain types even when the underlying data lives in another
    module's table, the same way `context_builder`'s `ContextPackageSourceView` projects fields
    from `projects`/`task_memory` types rather than returning them directly. Callers that need
    the full `Task` representation should call `task_memory`'s own API."""

    id: UUID
    status: str
    assigned_agent_id: UUID | None = None
    updated_at: datetime | None = None
