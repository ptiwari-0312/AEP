"""FastAPI dependency providers for the Metrics Service.

`get_metrics_service` obtains its `ProjectsProjectService` collaborator via the Project Service
module's own FastAPI dependency (`aep.modules.projects.api.dependencies.get_project_service`) —
this module's `api/` layer never imports `projects.repository`, even for wiring.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import get_db_session
from aep.core.security import get_current_user_id
from aep.modules.projects.api.dependencies import get_project_service
from aep.modules.projects.services import ProjectService

from ..repository.metric_repository import MetricRepository
from ..services.metrics_service import MetricsService

__all__ = ["get_current_user_id", "get_metrics_service"]


def get_metrics_service(
    session: AsyncSession = Depends(get_db_session),
    project_service: ProjectService = Depends(get_project_service),
) -> MetricsService:
    return MetricsService(MetricRepository(session), project_service)
