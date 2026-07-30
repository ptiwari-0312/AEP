"""FastAPI dependency providers for the Evaluation Framework.

`get_evaluation_service` obtains its `AgentRunService` collaborator via `orchestrator`'s own
FastAPI dependency (`aep.modules.orchestrator.api.dependencies.get_agent_run_service`) rather
than constructing its repositories itself — this module's `api/` layer never imports
`orchestrator.repository`, even for wiring purposes (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import get_db_session
from aep.core.security import get_current_user_id
from aep.modules.orchestrator.api.dependencies import get_agent_run_service
from aep.modules.orchestrator.services.agent_run_service import AgentRunService

from ..repository.evaluation_repository import EvaluationRepository
from ..repository.evaluation_result_repository import EvaluationResultRepository
from ..services.evaluation_service import EvaluationService
from ..services.evaluator_registry import EvaluatorRegistry

__all__ = ["get_current_user_id", "get_evaluation_service", "get_evaluator_registry"]


def get_evaluator_registry() -> EvaluatorRegistry:
    return EvaluatorRegistry()


def get_evaluation_service(
    session: AsyncSession = Depends(get_db_session),
    agent_run_service: AgentRunService = Depends(get_agent_run_service),
    evaluator_registry: EvaluatorRegistry = Depends(get_evaluator_registry),
) -> EvaluationService:
    return EvaluationService(
        EvaluationRepository(session),
        EvaluationResultRepository(session),
        agent_run_service,
        evaluator_registry,
    )
