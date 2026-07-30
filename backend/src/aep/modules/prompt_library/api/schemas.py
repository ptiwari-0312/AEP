"""Pydantic request/response schemas mirroring docs/architecture/04-api-design.md §6 —
no DB calls in this layer (docs/architecture/02-repo-design.md §2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PromptVariableSchema(BaseModel):
    # Needed on this nested model specifically, not just the response models that embed it:
    # Pydantic v2 validates each nested model independently, so `model_validate()` on an outer
    # response model doesn't propagate `from_attributes` down to a submodel that lacks its own
    # config — without this, validating a real `PromptVariable` dataclass instance (not a dict)
    # here raises `model_type` errors. Caught by an actual failing integration test.
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1)
    required: bool = True


class PromptTemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)


class PromptVersionCreateRequest(BaseModel):
    content: str = Field(min_length=1)
    variables: list[PromptVariableSchema] = Field(default_factory=list)
    activate: bool = False


class PromptVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prompt_template_id: UUID
    version_number: int
    content: str
    variables: list[PromptVariableSchema]
    is_active: bool
    created_by: UUID
    created_at: datetime | None


class PromptTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    owner_user_id: UUID
    created_at: datetime | None
    updated_at: datetime | None
    active_version: PromptVersionResponse | None = None


class PromptTemplateListResponse(BaseModel):
    items: list[PromptTemplateResponse]
    page: int
    page_size: int
    total: int
