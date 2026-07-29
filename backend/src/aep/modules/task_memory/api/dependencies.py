"""FastAPI dependency providers for the Task Memory Service.

`get_task_service` obtains its `ProjectsFeatureService` collaborator via the Project Service
module's own FastAPI dependency (`aep.modules.projects.api.dependencies.get_feature_service`)
rather than constructing `FeatureRepository`/`ProjectRepository` itself — this module's `api/`
layer never imports another module's `repository/`, even for composition/wiring purposes
(docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import get_db_session
from aep.core.security import get_current_user_id
from aep.modules.projects.api.dependencies import (
    get_feature_service as get_projects_feature_service,
)
from aep.modules.projects.services import FeatureService as ProjectsFeatureService

from ..repository.execution_history_repository import ExecutionHistoryRepository
from ..repository.task_dependency_repository import TaskDependencyRepository
from ..repository.task_repository import TaskRepository
from ..services.task_service import TaskService

__all__ = ["get_current_user_id", "get_task_service"]


def get_task_service(
    session: AsyncSession = Depends(get_db_session),
    projects_feature_service: ProjectsFeatureService = Depends(get_projects_feature_service),
) -> TaskService:
    return TaskService(
        TaskRepository(session),
        TaskDependencyRepository(session),
        ExecutionHistoryRepository(session),
        projects_feature_service,
    )
