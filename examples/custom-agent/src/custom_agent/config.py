"""Configuration schema for DocumentationAgent — validated at construction time, per the
plugin development guideline that every agent declares and validates its own config
(docs/architecture/09-engineering-standards.md §11)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentationAgentConfig(BaseModel):
    model: str = "default"
    max_tokens: int = Field(default=1024, gt=0)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    min_content_length: int = Field(default=20, ge=0)
