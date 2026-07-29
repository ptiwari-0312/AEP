"""FastAPI dependency providers for the Context Builder.

`get_context_builder_service` obtains its `TaskMemoryTaskService`/`ProjectsFeatureService`/
`ProjectsProjectService` collaborators via those modules' own FastAPI dependencies rather than
constructing their repositories itself — this module's `api/` layer never imports another
module's `repository/`, even for composition/wiring purposes
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
from aep.modules.projects.api.dependencies import (
    get_project_service as get_projects_project_service,
)
from aep.modules.projects.services import FeatureService as ProjectsFeatureService
from aep.modules.projects.services import ProjectService as ProjectsProjectService
from aep.modules.task_memory.api.dependencies import (
    get_task_service as get_task_memory_task_service,
)
from aep.modules.task_memory.services import TaskService as TaskMemoryTaskService

from ..repository.context_package_repository import ContextPackageRepository
from ..repository.context_package_source_repository import (
    ContextPackageSourceRepository,
)
from ..repository.source_document_repository import SourceDocumentRepository
from ..services.context_builder_service import ContextBuilderService

__all__ = ["get_context_builder_service", "get_current_user_id"]


def get_context_builder_service(
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskMemoryTaskService = Depends(get_task_memory_task_service),
    feature_service: ProjectsFeatureService = Depends(get_projects_feature_service),
    project_service: ProjectsProjectService = Depends(get_projects_project_service),
) -> ContextBuilderService:
    return ContextBuilderService(
        SourceDocumentRepository(session),
        ContextPackageRepository(session),
        ContextPackageSourceRepository(session),
        task_service,
        feature_service,
        project_service,
    )
