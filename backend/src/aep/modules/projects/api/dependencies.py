"""FastAPI dependency providers for the Project Service."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import get_db_session

from ..repository.feature_repository import FeatureRepository
from ..repository.git_repository_repository import GitRepositoryRepository
from ..repository.project_repository import ProjectRepository
from ..services.feature_service import FeatureService
from ..services.project_service import ProjectService

_PLACEHOLDER_SYSTEM_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


async def get_current_user_id() -> UUID:
    """Placeholder until `core/security.py` and the `auth` module exist
    (docs/architecture/02-repo-design.md §2) — returns a fixed system user id so these
    endpoints are exercisable end-to-end. This is NOT authentication; replace with a real
    JWT-derived dependency once the auth module exists. The request bodies these endpoints
    accept deliberately do NOT include an owner/creator field (matching
    docs/architecture/04-api-design.md §2 exactly) — that value always comes from this
    dependency, never from client input.
    """
    return _PLACEHOLDER_SYSTEM_USER_ID


def get_project_service(session: AsyncSession = Depends(get_db_session)) -> ProjectService:
    return ProjectService(ProjectRepository(session))


def get_feature_service(session: AsyncSession = Depends(get_db_session)) -> FeatureService:
    return FeatureService(FeatureRepository(session), ProjectRepository(session))


def get_git_repository_repository(
    session: AsyncSession = Depends(get_db_session),
) -> GitRepositoryRepository:
    return GitRepositoryRepository(session)
