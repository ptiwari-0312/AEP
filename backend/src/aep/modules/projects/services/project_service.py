"""Use-case orchestration for Projects (docs/architecture/02-repo-design.md §2's `services/`
layer) — thin by design. The slug-uniqueness check and archive-idempotency rule live here since
they're business rules, not persistence or HTTP concerns.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from ..domain.errors import (
    ProjectAlreadyArchivedError,
    ProjectNotFoundError,
    SlugAlreadyExistsError,
)
from ..domain.models import Project, ProjectStatus
from ..repository.project_repository import ProjectRepository


class ProjectService:
    def __init__(self, project_repository: ProjectRepository) -> None:
        self._projects = project_repository

    async def create_project(
        self,
        *,
        name: str,
        slug: str,
        owner_user_id: UUID,
        description: str | None = None,
        git_repository_id: UUID | None = None,
    ) -> Project:
        if await self._projects.get_by_slug(slug) is not None:
            raise SlugAlreadyExistsError(slug)
        project = Project(
            id=uuid4(),
            name=name,
            slug=slug,
            description=description,
            git_repository_id=git_repository_id,
            owner_user_id=owner_user_id,
        )
        return await self._projects.add(project)

    async def get_project(self, project_id: UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    async def list_projects(
        self,
        *,
        status: ProjectStatus | None = None,
        owner_user_id: UUID | None = None,
        name_contains: str | None = None,
        sort: str = "-created_at",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Project], int]:
        return await self._projects.list(
            status=status,
            owner_user_id=owner_user_id,
            name_contains=name_contains,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    async def update_project(
        self, project_id: UUID, *, name: str | None = None, description: str | None = None
    ) -> Project:
        project = await self.get_project(project_id)
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        return await self._projects.update(project)

    async def archive_project(self, project_id: UUID) -> Project:
        project = await self.get_project(project_id)
        if project.status == ProjectStatus.ARCHIVED:
            raise ProjectAlreadyArchivedError(project_id)
        project.status = ProjectStatus.ARCHIVED
        return await self._projects.update(project)

    async def attach_repository(self, project_id: UUID, *, git_repository_id: UUID) -> Project:
        project = await self.get_project(project_id)
        project.git_repository_id = git_repository_id
        return await self._projects.update(project)
