"""Pure domain entities and value objects for the Dashboard API
(docs/architecture/04-api-design.md §11; docs/architecture/02-repo-design.md §2's domain/
layer — zero framework imports).

This module owns no database table of its own — "composes the above; owns no domain data itself"
per the API design doc's own framing — so these are read-model DTOs assembled from other
modules' domain objects, not persisted entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class RecentEvaluationSummary:
    evaluation_id: UUID
    agent_run_id: UUID
    evaluator_type: str
    status: str
    created_at: datetime | None = None


@dataclass
class RecentAuditEventSummary:
    event_id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID
    actor_user_id: UUID | None = None
    actor_agent_id: UUID | None = None
    created_at: datetime | None = None


@dataclass
class DashboardOverview:
    """`GET /dashboard/overview`'s response (docs/architecture/04-api-design.md §11) —
    "explicitly allowed to be a few seconds stale" per the doc's own note; this reference
    implementation computes it fresh on every request (no caching layer), which satisfies that
    staleness allowance trivially but doesn't exploit it for performance — a real deployment
    would want the short-TTL cache the doc anticipates."""

    active_projects: int
    running_agents: int
    pending_approvals: int
    recent_evaluations: list[RecentEvaluationSummary] = field(default_factory=list)
    recent_audit_events: list[RecentAuditEventSummary] = field(default_factory=list)


@dataclass
class TaskGraphNode:
    task_id: UUID
    title: str
    task_type: str
    status: str
    priority: int
    assigned_agent_id: UUID | None = None


@dataclass
class TaskGraphEdge:
    task_id: UUID
    depends_on_task_id: UUID
    dependency_type: str


@dataclass
class TaskGraph:
    project_id: UUID
    nodes: list[TaskGraphNode] = field(default_factory=list)
    edges: list[TaskGraphEdge] = field(default_factory=list)


@dataclass
class RunningAgentSummary:
    """One row of `GET /dashboard/running-agents` (docs/architecture/04-api-design.md §11) — an
    `agent_run` enriched with the task/project/agent context the Running Agents screen's table
    needs (docs/architecture/08-dashboard-ux.md §7: "Task, Project, Agent Type, Provider/Model,
    Status, Attempt #, Elapsed Time"), so the frontend doesn't have to fan out per row."""

    agent_run_id: UUID
    task_id: UUID
    task_title: str
    project_id: UUID
    project_name: str
    agent_id: UUID
    agent_name: str
    agent_type: str
    provider: str
    model_name: str
    status: str
    attempt_number: int
    started_at: datetime | None = None
