"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §3 exactly."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import DependencyType, TaskStatus, TaskType


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    task_type: TaskType
    description: str | None = Field(default=None, max_length=10_000)
    priority: int = Field(default=0, ge=-32768, le=32767)


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    priority: int | None = Field(default=None, ge=-32768, le=32767)


class TaskStatusTransitionRequest(BaseModel):
    to_status: TaskStatus
    reason: str | None = None


class TaskDependencyCreateRequest(BaseModel):
    depends_on_task_id: UUID
    dependency_type: DependencyType = DependencyType.BLOCKS


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    feature_id: UUID
    title: str
    description: str | None
    task_type: TaskType
    status: TaskStatus
    assigned_agent_id: UUID | None
    priority: int
    created_at: datetime | None
    updated_at: datetime | None
    depends_on: list[UUID] = Field(default_factory=list)


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    next_cursor: str | None
    has_more: bool


class TaskDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    depends_on_task_id: UUID
    dependency_type: DependencyType
    created_at: datetime | None


class ExecutionHistoryEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    from_status: TaskStatus | None
    to_status: TaskStatus
    changed_by_user_id: UUID | None
    changed_by_agent_id: UUID | None
    reason: str | None
    created_at: datetime | None


class ExecutionHistoryListResponse(BaseModel):
    items: list[ExecutionHistoryEntryResponse]
    next_cursor: str | None
    has_more: bool
