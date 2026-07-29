"""FastAPI dependency providers for the Project Service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import get_db_session
from aep.core.security import get_current_user_id

from ..repository.feature_repository import FeatureRepository
from ..repository.git_repository_repository import GitRepositoryRepository
from ..repository.project_repository import ProjectRepository
from ..services.feature_service import FeatureService
from ..services.project_service import ProjectService

__all__ = [
    "get_current_user_id",
    "get_feature_service",
    "get_git_repository_repository",
    "get_project_service",
]


def get_project_service(session: AsyncSession = Depends(get_db_session)) -> ProjectService:
    return ProjectService(ProjectRepository(session))


def get_feature_service(session: AsyncSession = Depends(get_db_session)) -> FeatureService:
    return FeatureService(FeatureRepository(session), ProjectRepository(session))


def get_git_repository_repository(
    session: AsyncSession = Depends(get_db_session),
) -> GitRepositoryRepository:
    return GitRepositoryRepository(session)
