"""FastAPI dependency providers for the Dashboard API.

Every collaborator is obtained via the *other* module's own `api/dependencies.py` provider
functions — never by importing any module's `repository/` directly
(docs/architecture/02-repo-design.md §2) — the same pattern every other module's `api/
dependencies.py` already follows, just with more collaborators than usual since composition is
this module's entire job.
"""

from __future__ import annotations

from fastapi import Depends

from aep.core.security import get_current_user_id
from aep.modules.auth.api.dependencies import get_audit_service
from aep.modules.auth.services import AuditService
from aep.modules.evaluation.api.dependencies import get_evaluation_service
from aep.modules.evaluation.services.evaluation_service import EvaluationService
from aep.modules.orchestrator.api.dependencies import (
    get_agent_run_service,
    get_agent_service,
)
from aep.modules.orchestrator.services.agent_run_service import AgentRunService
from aep.modules.orchestrator.services.agent_service import AgentService
from aep.modules.projects.api.dependencies import (
    get_feature_service,
    get_project_service,
)
from aep.modules.projects.services import FeatureService, ProjectService
from aep.modules.task_memory.api.dependencies import get_task_service
from aep.modules.task_memory.services import TaskService

from ..services.dashboard_service import DashboardService

__all__ = ["get_current_user_id", "get_dashboard_service"]


def get_dashboard_service(
    project_service: ProjectService = Depends(get_project_service),
    feature_service: FeatureService = Depends(get_feature_service),
    task_service: TaskService = Depends(get_task_service),
    agent_run_service: AgentRunService = Depends(get_agent_run_service),
    agent_service: AgentService = Depends(get_agent_service),
    evaluation_service: EvaluationService = Depends(get_evaluation_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> DashboardService:
    return DashboardService(
        project_service,
        feature_service,
        task_service,
        agent_run_service,
        agent_service,
        evaluation_service,
        audit_service,
    )
