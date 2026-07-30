"""FastAPI dependency providers for the Agent Orchestrator.

Cross-module collaborators are obtained via the *other* module's own `api/dependencies.py`
provider functions — never by importing its `repository/` directly
(docs/architecture/02-repo-design.md §2) — the same pattern every other module's `api/
dependencies.py` already follows.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.db import get_db_session
from aep.core.security import get_current_user_id
from aep.modules.auth.api.dependencies import get_audit_service
from aep.modules.auth.services import AuditService
from aep.modules.context_builder.api.dependencies import get_context_builder_service
from aep.modules.context_builder.services import ContextBuilderService
from aep.modules.task_memory.api.dependencies import (
    get_task_service as get_task_memory_task_service,
)
from aep.modules.task_memory.services import TaskService as TaskMemoryTaskService

from ..repository.agent_repository import AgentRepository
from ..repository.agent_run_repository import AgentRunRepository
from ..services.agent_registry import AgentRegistry
from ..services.agent_run_service import AgentRunService
from ..services.agent_service import AgentService
from ..services.run_events import RunEventBroker, get_run_event_broker
from ..services.run_registry import RunRegistry, get_run_registry
from ..services.task_review_service import TaskReviewService

__all__ = [
    "get_agent_registry",
    "get_agent_run_service",
    "get_agent_service",
    "get_current_user_id",
    "get_task_review_service",
]


def get_agent_service(session: AsyncSession = Depends(get_db_session)) -> AgentService:
    return AgentService(AgentRepository(session))


def get_agent_registry() -> AgentRegistry:
    return AgentRegistry()


def get_agent_run_service(
    session: AsyncSession = Depends(get_db_session),
    task_service: TaskMemoryTaskService = Depends(get_task_memory_task_service),
    context_builder_service: ContextBuilderService = Depends(get_context_builder_service),
    agent_registry: AgentRegistry = Depends(get_agent_registry),
    run_registry: RunRegistry = Depends(get_run_registry),
    run_event_broker: RunEventBroker = Depends(get_run_event_broker),
) -> AgentRunService:
    return AgentRunService(
        AgentRepository(session),
        AgentRunRepository(session),
        task_service,
        context_builder_service,
        agent_registry,
        run_registry,
        run_event_broker,
    )


def get_task_review_service(
    task_service: TaskMemoryTaskService = Depends(get_task_memory_task_service),
    audit_service: AuditService = Depends(get_audit_service),
) -> TaskReviewService:
    return TaskReviewService(task_service, audit_service)
