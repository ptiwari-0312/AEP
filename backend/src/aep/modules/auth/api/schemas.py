"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §1 and §10
exactly."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..domain.models import UserStatus


class LoginRequest(BaseModel):
    provider: Literal["github", "google", "okta"]
    code: str = Field(min_length=1)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str
    status: UserStatus
    created_at: datetime | None


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    user: UserSummary


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class CurrentUserResponse(BaseModel):
    id: UUID
    email: str
    display_name: str
    status: UserStatus
    roles: list[str]
    created_at: datetime | None


class UserListResponse(BaseModel):
    items: list[UserSummary]
    page: int
    page_size: int
    total: int


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    status: UserStatus | None = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    created_at: datetime | None


class GrantRoleRequest(BaseModel):
    role_id: UUID


class UserRoleResponse(BaseModel):
    user_id: UUID
    role_id: UUID
    granted_at: datetime | None
    granted_by: UUID | None


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    entity_type: str
    entity_id: UUID
    actor_user_id: UUID | None
    actor_agent_id: UUID | None
    payload: dict[str, Any]
    created_at: datetime | None


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse]
    next_cursor: str | None
    has_more: bool
