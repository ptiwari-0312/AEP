"""Data access for `git_repositories` (docs/architecture/03-db-design.md §3). Owned by the
Project Service since nothing else references it and a repo is attached to exactly one project
at a time via `PUT /projects/{projectId}/repository` (docs/architecture/04-api-design.md §2).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import GitRepository
from .models import GitRepositoryModel


class GitRepositoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, repository: GitRepository) -> GitRepository:
        model = GitRepositoryModel(
            id=repository.id,
            name=repository.name,
            url=repository.url,
            provider=repository.provider,
            default_branch=repository.default_branch,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, repository_id: UUID) -> GitRepository | None:
        model = await self._session.get(GitRepositoryModel, repository_id)
        return _to_domain(model) if model else None

    async def get_by_url(self, url: str) -> GitRepository | None:
        result = await self._session.execute(
            select(GitRepositoryModel).where(GitRepositoryModel.url == url)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None


def _to_domain(model: GitRepositoryModel) -> GitRepository:
    return GitRepository(
        id=model.id,
        name=model.name,
        url=model.url,
        provider=model.provider,
        default_branch=model.default_branch,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
