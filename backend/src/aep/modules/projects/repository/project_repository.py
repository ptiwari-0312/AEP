"""Data access for `projects` (docs/architecture/03-db-design.md §4). The only place in this
module allowed to import SQLAlchemy for this table (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Project, ProjectStatus
from .models import ProjectModel

_SORTABLE_FIELDS = {"name": ProjectModel.name, "created_at": ProjectModel.created_at}


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> Project:
        model = _to_model(project)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, project_id: UUID) -> Project | None:
        model = await self._session.get(ProjectModel, project_id)
        return _to_domain(model) if model else None

    async def get_by_slug(self, slug: str) -> Project | None:
        result = await self._session.execute(select(ProjectModel).where(ProjectModel.slug == slug))
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def list(
        self,
        *,
        status: ProjectStatus | None = None,
        owner_user_id: UUID | None = None,
        name_contains: str | None = None,
        sort: str = "-created_at",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Project], int]:
        query = select(ProjectModel)
        count_query = select(func.count()).select_from(ProjectModel)
        if status is not None:
            query = query.where(ProjectModel.status == status.value)
            count_query = count_query.where(ProjectModel.status == status.value)
        if owner_user_id is not None:
            query = query.where(ProjectModel.owner_user_id == owner_user_id)
            count_query = count_query.where(ProjectModel.owner_user_id == owner_user_id)
        if name_contains:
            query = query.where(ProjectModel.name.ilike(f"%{name_contains}%"))
            count_query = count_query.where(ProjectModel.name.ilike(f"%{name_contains}%"))

        total = (await self._session.execute(count_query)).scalar_one()

        field_name = sort.lstrip("-")
        column = _SORTABLE_FIELDS.get(field_name, ProjectModel.created_at)
        query = query.order_by(column.desc() if sort.startswith("-") else column.asc())
        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        return [_to_domain(m) for m in result.scalars().all()], total

    async def update(self, project: Project) -> Project:
        model = await self._session.get(ProjectModel, project.id)
        if model is None:
            raise ValueError(f"project {project.id} does not exist — call add() first")
        model.name = project.name
        model.description = project.description
        model.status = project.status.value
        model.git_repository_id = project.git_repository_id
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)


def _to_domain(model: ProjectModel) -> Project:
    return Project(
        id=model.id,
        name=model.name,
        slug=model.slug,
        description=model.description,
        git_repository_id=model.git_repository_id,
        owner_user_id=model.owner_user_id,
        status=ProjectStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_model(project: Project) -> ProjectModel:
    return ProjectModel(
        id=project.id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        git_repository_id=project.git_repository_id,
        owner_user_id=project.owner_user_id,
        status=project.status.value,
    )
