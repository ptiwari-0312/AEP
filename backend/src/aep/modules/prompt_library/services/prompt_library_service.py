"""Use-case orchestration for prompt templates and their versions
(docs/architecture/04-api-design.md §6). One combined service for both tightly-coupled tables —
same shape as `evaluation.EvaluationService` handling `evaluations`+`evaluation_results` — rather
than a `ProjectService`/`FeatureService`-style split, since a version is never addressed except
through its parent template (`{templateId}/versions/{versionNumber}`, never a bare version id in
any URL) and "get a template" always wants its active version inline.

No cross-module collaborators: unlike every other module built so far, this one is fully
self-contained — `owner_user_id`/`created_by` are `UUID`s obtained from the caller (`auth`'s
`get_current_user_id`), never resolved against `auth`'s `users` table (same deferred-FK stance as
`owner_user_id` elsewhere), and nothing else in the schema references `prompt_templates`/
`prompt_versions` from this side.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from ..domain.errors import (
    PromptTemplateNameExistsError,
    PromptTemplateNotFoundError,
    PromptVersionNotFoundError,
    VersionAlreadyActiveError,
)
from ..domain.models import PromptTemplate, PromptVariable, PromptVersion
from ..domain.rendering import render as render_content
from ..domain.rendering import validate_variables_declared
from ..repository.prompt_template_repository import PromptTemplateRepository
from ..repository.prompt_version_repository import PromptVersionRepository


class PromptLibraryService:
    def __init__(
        self,
        template_repository: PromptTemplateRepository,
        version_repository: PromptVersionRepository,
    ) -> None:
        self._templates = template_repository
        self._versions = version_repository

    async def create_template(
        self, *, name: str, owner_user_id: UUID, description: str | None = None
    ) -> PromptTemplate:
        if await self._templates.get_by_name(name) is not None:
            raise PromptTemplateNameExistsError(name)
        template = PromptTemplate(
            id=uuid4(), name=name, description=description, owner_user_id=owner_user_id
        )
        return await self._templates.add(template)

    async def get_template(self, template_id: UUID) -> PromptTemplate:
        template = await self._templates.get_by_id(template_id)
        if template is None:
            raise PromptTemplateNotFoundError(template_id)
        return template

    async def get_template_with_active_version(
        self, template_id: UUID
    ) -> tuple[PromptTemplate, PromptVersion | None]:
        template = await self.get_template(template_id)
        active_version = await self._versions.get_active_for_template(template_id)
        return template, active_version

    async def list_templates(
        self, *, limit: int = 20, offset: int = 0
    ) -> tuple[list[PromptTemplate], int]:
        return await self._templates.list(limit=limit, offset=offset)

    async def create_version(
        self,
        template_id: UUID,
        *,
        content: str,
        created_by: UUID,
        variables: list[PromptVariable] | None = None,
        activate: bool = False,
    ) -> PromptVersion:
        await self.get_template(template_id)
        variables = variables or []
        validate_variables_declared(content, variables)

        next_version_number = await self._versions.get_max_version_number(template_id) + 1
        version = await self._versions.add(
            PromptVersion(
                id=uuid4(),
                prompt_template_id=template_id,
                version_number=next_version_number,
                content=content,
                created_by=created_by,
                variables=variables,
            )
        )
        if activate:
            version = await self._activate(template_id, version)
        return version

    async def list_versions(self, template_id: UUID) -> list[PromptVersion]:
        await self.get_template(template_id)
        return await self._versions.list_for_template(template_id)

    async def get_version(self, template_id: UUID, version_number: int) -> PromptVersion:
        await self.get_template(template_id)
        version = await self._versions.get_by_template_and_version_number(
            template_id, version_number
        )
        if version is None:
            raise PromptVersionNotFoundError(template_id, version_number)
        return version

    async def activate_version(self, template_id: UUID, version_number: int) -> PromptVersion:
        version = await self.get_version(template_id, version_number)
        if version.is_active:
            raise VersionAlreadyActiveError(template_id, version_number)
        return await self._activate(template_id, version)

    async def render_version(
        self, template_id: UUID, version_number: int, values: dict[str, Any]
    ) -> str:
        version = await self.get_version(template_id, version_number)
        return render_content(version.content, version.variables, values)

    async def _activate(self, template_id: UUID, version: PromptVersion) -> PromptVersion:
        """Deactivates the current active version (if any and different from `version`) before
        activating `version` — strictly sequential flushes, never both rows `is_active=True` at
        once, so the DB's partial-unique-active-version index (repository/models.py) is never
        even transiently violated by this, its one legitimate caller."""
        current_active = await self._versions.get_active_for_template(template_id)
        if current_active is not None and current_active.id != version.id:
            await self._versions.set_active(current_active.id, is_active=False)
        return await self._versions.set_active(version.id, is_active=True)
