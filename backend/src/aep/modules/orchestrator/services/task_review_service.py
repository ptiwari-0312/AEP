"""The human-approval gate (docs/architecture/04-api-design.md §5:
`approve`/`reject`/`merge`) — thin wrappers over `task_memory`'s own status state machine, which
already encodes the legal transitions (`awaiting_approval -> approved|rejected`,
`approved -> merged`) and the dependency-satisfaction gate. This service's only added value is
translating the reviewer's action into the right `to_status` and (for `approve`, per the API
design doc's explicit note) writing the one illustrative audit trail entry.
"""

from __future__ import annotations

from uuid import UUID

from aep.modules.auth.services import AuditService
from aep.modules.task_memory.domain.errors import (
    IllegalTaskStatusTransitionError as TaskMemoryIllegalTransitionError,
)
from aep.modules.task_memory.domain.errors import (
    TaskNotFoundError as TaskMemoryTaskNotFoundError,
)
from aep.modules.task_memory.domain.models import TaskStatus as TaskMemoryTaskStatus
from aep.modules.task_memory.services import TaskService as TaskMemoryTaskService

from ..domain.errors import TaskNotFoundError, TaskTransitionNotAllowedError
from ..domain.models import TaskSummary


class TaskReviewService:
    def __init__(self, task_service: TaskMemoryTaskService, audit_service: AuditService) -> None:
        self._tasks = task_service
        self._audit = audit_service

    async def approve(
        self, task_id: UUID, *, reviewer_user_id: UUID, comment: str | None = None
    ) -> TaskSummary:
        task = await self._transition(
            task_id,
            to_status=TaskMemoryTaskStatus.APPROVED,
            reason=comment,
            changed_by_user_id=reviewer_user_id,
        )
        # The one explicit audit-write requirement in docs/architecture/04-api-design.md §5's
        # `POST .../approve` doc — reject/merge aren't documented as writing one, so they don't
        # here either (see this module's README).
        await self._audit.record_event(
            event_type="task.approved",
            entity_type="task",
            entity_id=task_id,
            actor_user_id=reviewer_user_id,
            payload={"comment": comment} if comment else {},
        )
        return task

    async def reject(
        self, task_id: UUID, *, reviewer_user_id: UUID, comment: str | None = None
    ) -> TaskSummary:
        return await self._transition(
            task_id,
            to_status=TaskMemoryTaskStatus.REJECTED,
            reason=comment,
            changed_by_user_id=reviewer_user_id,
        )

    async def merge(self, task_id: UUID, *, actor_user_id: UUID) -> TaskSummary:
        return await self._transition(
            task_id, to_status=TaskMemoryTaskStatus.MERGED, changed_by_user_id=actor_user_id
        )

    async def _transition(
        self,
        task_id: UUID,
        *,
        to_status: TaskMemoryTaskStatus,
        changed_by_user_id: UUID,
        reason: str | None = None,
    ) -> TaskSummary:
        try:
            task = await self._tasks.transition_status(
                task_id,
                to_status=to_status,
                reason=reason,
                changed_by_user_id=changed_by_user_id,
            )
        except TaskMemoryTaskNotFoundError as exc:
            raise TaskNotFoundError(task_id) from exc
        except TaskMemoryIllegalTransitionError as exc:
            raise TaskTransitionNotAllowedError(task_id, str(exc)) from exc
        return TaskSummary(
            id=task.id,
            status=task.status.value,
            assigned_agent_id=task.assigned_agent_id,
            updated_at=task.updated_at,
        )
