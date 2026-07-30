"""Pydantic response schemas mirroring docs/architecture/04-api-design.md §11 — no DB calls in
this layer (docs/architecture/02-repo-design.md §2). Read-only: this module has no request
bodies of its own, since every endpoint it exposes is a `GET`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RecentEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    evaluation_id: UUID
    agent_run_id: UUID
    evaluator_type: str
    status: str
    created_at: datetime | None


class RecentAuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID
    actor_user_id: UUID | None
    actor_agent_id: UUID | None
    created_at: datetime | None


class DashboardOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    active_projects: int
    running_agents: int
    pending_approvals: int
    recent_evaluations: list[RecentEvaluationResponse]
    recent_audit_events: list[RecentAuditEventResponse]


class TaskGraphNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    title: str
    task_type: str
    status: str
    priority: int
    assigned_agent_id: UUID | None


class TaskGraphEdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: UUID
    depends_on_task_id: UUID
    dependency_type: str


class TaskGraphResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    nodes: list[TaskGraphNodeResponse]
    edges: list[TaskGraphEdgeResponse]


class RunningAgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    started_at: datetime | None
