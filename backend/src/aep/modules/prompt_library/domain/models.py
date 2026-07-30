"""Pure domain entities and value objects for the Prompt Library
(docs/architecture/03-db-design.md §10-11; docs/architecture/09-engineering-standards.md §9;
docs/architecture/02-repo-design.md §2's domain/ layer — zero framework imports).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass
class PromptVariable:
    """One entry of `prompt_versions.variables` (DB design §11) — a declared name plus whether a
    caller must supply it at render time."""

    name: str
    required: bool = True


@dataclass
class PromptTemplate:
    id: UUID
    name: str
    owner_user_id: UUID
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class PromptVersion:
    """Immutable once created (docs/architecture/09-engineering-standards.md §9) — the only
    mutation ever made to an existing row is `is_active` flipping via `activate()`
    (docs/architecture/04-api-design.md §6's own note: "there is deliberately no PATCH on a
    version")."""

    id: UUID
    prompt_template_id: UUID
    version_number: int
    content: str
    created_by: UUID
    variables: list[PromptVariable] = field(default_factory=list)
    is_active: bool = False
    created_at: datetime | None = None
