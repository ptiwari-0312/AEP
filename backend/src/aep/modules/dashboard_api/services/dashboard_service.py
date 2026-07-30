"""Composes the other modules' public `services/` into the three read-models
docs/architecture/04-api-design.md §11 defines — this module's entire job, since it "owns no
domain data itself." Depends on `projects` (`ProjectService`/`FeatureService`), `task_memory`
(`TaskService`), `orchestrator` (`AgentRunService`/`AgentService`), `evaluation`
(`EvaluationService`), and `auth` (`AuditService`) — more collaborators than any other module in
this codebase, which is the expected shape of a module whose entire purpose is composition, not
a violation of the "keep dependencies narrow" instinct every other module followed.

Three small new methods were added to *other* modules while building this one —
`task_memory.TaskService.count_tasks_by_status()`, `orchestrator.AgentRunService.
count_runs_by_statuses()`/`list_runs_by_statuses()`, and `evaluation.EvaluationService.
list_recent_evaluations()` — because every existing listing method on those services is scoped
to one parent (a feature, a task, an agent run) and this module's overview/running-agents
read-models need *global* counts/listings across every parent. See each module's own README for
the added method's docstring.
"""

from __future__ import annotations

from uuid import UUID

from aep.modules.auth.services import AuditService
from aep.modules.evaluation.services.evaluation_service import EvaluationService
from aep.modules.orchestrator.domain.models import (
    AgentRunStatus as OrchestratorAgentRunStatus,
)
from aep.modules.orchestrator.services.agent_run_service import (
    AgentRunService as OrchestratorAgentRunService,
)
from aep.modules.orchestrator.services.agent_service import (
    AgentService as OrchestratorAgentService,
)
from aep.modules.projects.domain.errors import (
    ProjectNotFoundError as ProjectsProjectNotFoundError,
)
from aep.modules.projects.domain.models import ProjectStatus
from aep.modules.projects.services import FeatureService as ProjectsFeatureService
from aep.modules.projects.services import ProjectService as ProjectsProjectService
from aep.modules.task_memory.domain.models import Task as TaskMemoryTask
from aep.modules.task_memory.domain.models import TaskStatus as TaskMemoryTaskStatus
from aep.modules.task_memory.services import TaskService as TaskMemoryTaskService

from ..domain.errors import ProjectNotFoundError
from ..domain.models import (
    DashboardOverview,
    RecentAuditEventSummary,
    RecentEvaluationSummary,
    RunningAgentSummary,
    TaskGraph,
    TaskGraphEdge,
    TaskGraphNode,
)

_RUNNING_STATUSES = [OrchestratorAgentRunStatus.RUNNING, OrchestratorAgentRunStatus.RETRYING]


class DashboardService:
    def __init__(
        self,
        project_service: ProjectsProjectService,
        feature_service: ProjectsFeatureService,
        task_service: TaskMemoryTaskService,
        agent_run_service: OrchestratorAgentRunService,
        agent_service: OrchestratorAgentService,
        evaluation_service: EvaluationService,
        audit_service: AuditService,
    ) -> None:
        self._projects = project_service
        self._features = feature_service
        self._tasks = task_service
        self._agent_runs = agent_run_service
        self._agents = agent_service
        self._evaluations = evaluation_service
        self._audit = audit_service

    async def get_overview(self) -> DashboardOverview:
        _projects, active_count = await self._projects.list_projects(
            status=ProjectStatus.ACTIVE, limit=1, offset=0
        )
        running_count = await self._agent_runs.count_runs_by_statuses(_RUNNING_STATUSES)
        pending_count = await self._tasks.count_tasks_by_status(
            TaskMemoryTaskStatus.AWAITING_APPROVAL
        )
        recent_evaluations = await self._evaluations.list_recent_evaluations(limit=10)
        recent_audit_events, _cursor, _has_more = await self._audit.list_events(limit=10)

        return DashboardOverview(
            active_projects=active_count,
            running_agents=running_count,
            pending_approvals=pending_count,
            recent_evaluations=[
                RecentEvaluationSummary(
                    evaluation_id=evaluation.id,
                    agent_run_id=evaluation.agent_run_id,
                    evaluator_type=evaluation.evaluator_type.value,
                    status=evaluation.status.value,
                    created_at=evaluation.created_at,
                )
                for evaluation in recent_evaluations
            ],
            recent_audit_events=[
                RecentAuditEventSummary(
                    event_id=event.id,
                    event_type=event.event_type,
                    entity_type=event.entity_type,
                    entity_id=event.entity_id,
                    actor_user_id=event.actor_user_id,
                    actor_agent_id=event.actor_agent_id,
                    created_at=event.created_at,
                )
                for event in recent_audit_events
            ],
        )

    async def get_task_graph(self, project_id: UUID) -> TaskGraph:
        try:
            features = await self._features.list_features_for_project(project_id)
        except ProjectsProjectNotFoundError as exc:
            raise ProjectNotFoundError(project_id) from exc

        nodes: list[TaskGraphNode] = []
        edges: list[TaskGraphEdge] = []
        for feature in features:
            tasks = await self._list_all_tasks_for_feature(feature.id)
            for task in tasks:
                nodes.append(
                    TaskGraphNode(
                        task_id=task.id,
                        title=task.title,
                        task_type=task.task_type.value,
                        status=task.status.value,
                        priority=task.priority,
                        assigned_agent_id=task.assigned_agent_id,
                    )
                )
                dependencies = await self._tasks.list_dependencies(task.id)
                edges.extend(
                    TaskGraphEdge(
                        task_id=dependency.task_id,
                        depends_on_task_id=dependency.depends_on_task_id,
                        dependency_type=dependency.dependency_type.value,
                    )
                    for dependency in dependencies
                )
        return TaskGraph(project_id=project_id, nodes=nodes, edges=edges)

    async def _list_all_tasks_for_feature(self, feature_id: UUID) -> list[TaskMemoryTask]:
        """Loops through every cursor page rather than taking one — "the full graph" (the API
        design doc's own words for this endpoint) means every task, not just the first 100."""
        all_tasks: list[TaskMemoryTask] = []
        cursor: str | None = None
        while True:
            tasks, cursor, has_more = await self._tasks.list_tasks_for_feature(
                feature_id, cursor=cursor, limit=100
            )
            all_tasks.extend(tasks)
            if not has_more:
                break
        return all_tasks

    async def list_running_agents(self) -> list[RunningAgentSummary]:
        """"Across projects the caller can see" per the API design doc — but no per-project
        visibility/access-control concept exists anywhere in this codebase yet (role enforcement
        is a documented gap in every module), so this reference implementation returns every
        running/retrying run system-wide, the same "no role enforcement yet" stance every other
        module already takes."""
        runs = await self._agent_runs.list_runs_by_statuses(_RUNNING_STATUSES, limit=100)
        summaries = []
        for run in runs:
            task = await self._tasks.get_task(run.task_id)
            feature = await self._features.get_feature(task.feature_id)
            project = await self._projects.get_project(feature.project_id)
            agent = await self._agents.get_agent(run.agent_id)
            summaries.append(
                RunningAgentSummary(
                    agent_run_id=run.id,
                    task_id=task.id,
                    task_title=task.title,
                    project_id=project.id,
                    project_name=project.name,
                    agent_id=agent.id,
                    agent_name=agent.name,
                    agent_type=agent.agent_type.value,
                    provider=run.provider,
                    model_name=run.model_name,
                    status=run.status.value,
                    attempt_number=run.attempt_number,
                    started_at=run.started_at,
                )
            )
        return summaries
