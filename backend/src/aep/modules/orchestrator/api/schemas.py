"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §5 —
no DB or provider calls in this layer (docs/architecture/02-repo-design.md §2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import AgentRunStatus, AgentType

_ProviderLiteral = Literal["claude", "openai", "gemini", "vertex_ai"]


class AgentRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    agent_type: AgentType
    version: str = Field(min_length=1, max_length=50)
    config: dict[str, Any] = Field(default_factory=dict)


class AgentUpdateRequest(BaseModel):
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    agent_type: AgentType
    version: str
    is_enabled: bool
    config: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime | None


class AgentListResponse(BaseModel):
    items: list[AgentResponse]
    page: int
    page_size: int
    total: int


class AssignAgentRequest(BaseModel):
    agent_id: UUID


class TaskSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    assigned_agent_id: UUID | None
    updated_at: datetime | None


class StartRunRequest(BaseModel):
    provider: _ProviderLiteral
    model_name: str = Field(min_length=1, max_length=100)
    context_package_id: UUID


class StartRunResponse(BaseModel):
    agent_run_id: str
    status: Literal["queued"] = "queued"


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    task_id: UUID
    context_package_id: UUID | None
    provider: str
    model_name: str
    status: AgentRunStatus
    attempt_number: int
    started_at: datetime | None
    completed_at: datetime | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    error_message: str | None
    created_at: datetime | None


class AgentRunListResponse(BaseModel):
    items: list[AgentRunResponse]
    next_cursor: str | None
    has_more: bool


class ApproveTaskRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=10_000)


class RejectTaskRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=10_000)
