"""Use-case orchestration for triggering evaluators and aggregating the quality gate
(docs/architecture/04-api-design.md §7; docs/architecture/07-evaluation-framework.md).

Cross-module composition: this module talks only to `orchestrator`'s public `AgentRunService` —
never `task_memory` directly, and never any other module's `repository/`. Confirming a task
exists (for the quality-gate endpoint) is `orchestrator.AgentRunService.get_latest_run_for_task()`'s
own job; this module just translates whatever it raises.

Scheduling (docs/architecture/07-evaluation-framework.md §4, ADR-EV2): requested evaluator types
are split by `aep_eval_sdk.category_of()` into deterministic and LLM-assisted waves, each wave run
concurrently via `asyncio.gather`. There's no per-project `EvaluationPolicy` store in this
reference backend (the design doc itself only says this is "project-level configuration," not
where it lives) — every requested evaluator is treated as required, matching §7's aggregation
formula's own wording, and `fail_fast` scheduling (skip wave 2 if a required wave-1 evaluator
failed) is a real, tested capability of this service but isn't reachable through the current HTTP
contract, since `POST .../evaluations`'s request body only carries `evaluator_types` — no policy
field to select it.
"""

from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID, uuid4

from aep_eval_sdk import AgentRunContext, EvaluationReport, category_of
from aep_eval_sdk import EvaluatorCategory as SdkEvaluatorCategory

from aep.modules.orchestrator.domain.errors import (
    AgentRunNotFoundError as OrchestratorAgentRunNotFoundError,
)
from aep.modules.orchestrator.domain.errors import (
    TaskNotFoundError as OrchestratorTaskNotFoundError,
)
from aep.modules.orchestrator.domain.models import (
    AgentRunStatus as OrchestratorAgentRunStatus,
)
from aep.modules.orchestrator.services.agent_run_service import AgentRunService

from ..domain.errors import (
    AgentRunNotFoundError,
    AgentRunNotSucceededError,
    EvaluationNotFoundError,
    EvaluatorTypeNotRegisteredError,
    TaskNotFoundError,
)
from ..domain.models import (
    Evaluation,
    EvaluationResult,
    EvaluatorType,
    QualityGateEvaluationSummary,
    QualityGateResult,
)
from ..repository.evaluation_repository import EvaluationRepository
from ..repository.evaluation_result_repository import EvaluationResultRepository
from .evaluator_registry import EvaluatorRegistry

_PENDING_STATUSES = {"pending", "running"}


class EvaluationService:
    def __init__(
        self,
        evaluation_repository: EvaluationRepository,
        evaluation_result_repository: EvaluationResultRepository,
        agent_run_service: AgentRunService,
        evaluator_registry: EvaluatorRegistry,
    ) -> None:
        self._evaluations = evaluation_repository
        self._results = evaluation_result_repository
        self._agent_runs = agent_run_service
        self._registry = evaluator_registry

    async def trigger_evaluations(
        self,
        agent_run_id: UUID,
        *,
        evaluator_types: list[EvaluatorType],
        fail_fast: bool = False,
    ) -> list[Evaluation]:
        try:
            run = await self._agent_runs.get_run(agent_run_id)
        except OrchestratorAgentRunNotFoundError as exc:
            raise AgentRunNotFoundError(agent_run_id) from exc
        if run.status != OrchestratorAgentRunStatus.SUCCEEDED:
            raise AgentRunNotSucceededError(agent_run_id)

        for evaluator_type in evaluator_types:
            if not self._registry.is_registered(evaluator_type):
                raise EvaluatorTypeNotRegisteredError(evaluator_type)

        duration_seconds = None
        if run.started_at is not None and run.completed_at is not None:
            duration_seconds = (run.completed_at - run.started_at).total_seconds()
        context = AgentRunContext(
            agent_run_id=run.id,
            task_id=run.task_id,
            provider=run.provider,
            model_name=run.model_name,
            metadata={
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "cost_usd": run.cost_usd,
                "duration_seconds": duration_seconds,
            },
        )

        deterministic_types = [
            t for t in evaluator_types if category_of(t) == SdkEvaluatorCategory.DETERMINISTIC
        ]
        llm_assisted_types = [
            t for t in evaluator_types if category_of(t) == SdkEvaluatorCategory.LLM_ASSISTED
        ]

        evaluations: list[Evaluation] = []
        evaluations.extend(await self._run_wave(deterministic_types, context))
        if fail_fast and any(e.status.value == "failed" for e in evaluations):
            return evaluations
        evaluations.extend(await self._run_wave(llm_assisted_types, context))
        return evaluations

    async def _run_wave(
        self, evaluator_types: list[EvaluatorType], context: AgentRunContext
    ) -> list[Evaluation]:
        if not evaluator_types:
            return []
        reports = await asyncio.gather(
            *(self._registry.create(t).run(context) for t in evaluator_types)
        )
        return [
            await self._persist(context.agent_run_id, evaluator_type, report)
            for evaluator_type, report in zip(evaluator_types, reports, strict=True)
        ]

    async def _persist(
        self, agent_run_id: UUID, evaluator_type: EvaluatorType, report: EvaluationReport
    ) -> Evaluation:
        evaluation = await self._evaluations.add(
            Evaluation(
                id=uuid4(),
                agent_run_id=agent_run_id,
                evaluator_type=evaluator_type,
                status=report.status,
                started_at=report.started_at,
                completed_at=report.completed_at,
            )
        )
        if report.scores:
            results = [
                EvaluationResult(
                    id=uuid4(),
                    evaluation_id=evaluation.id,
                    metric_name=score.metric_name,
                    score=round(score.score, 4),
                    threshold=round(score.threshold, 4) if score.threshold is not None else None,
                    passed=score.passed,
                    details=score.details,
                )
                for score in report.scores
            ]
            await self._results.add_many(results)
        return evaluation

    async def get_evaluation(self, evaluation_id: UUID) -> Evaluation:
        evaluation = await self._evaluations.get_by_id(evaluation_id)
        if evaluation is None:
            raise EvaluationNotFoundError(evaluation_id)
        return evaluation

    async def list_evaluations_for_run(self, agent_run_id: UUID) -> list[Evaluation]:
        try:
            await self._agent_runs.get_run(agent_run_id)
        except OrchestratorAgentRunNotFoundError as exc:
            raise AgentRunNotFoundError(agent_run_id) from exc
        return await self._evaluations.list_for_agent_run(agent_run_id)

    async def list_results_for_evaluation(self, evaluation_id: UUID) -> list[EvaluationResult]:
        await self.get_evaluation(evaluation_id)
        return await self._results.list_for_evaluation(evaluation_id)

    async def list_recent_evaluations(self, *, limit: int = 10) -> list[Evaluation]:
        """Global listing across every agent run — backs `dashboard_api`'s overview endpoint."""
        return await self._evaluations.list_recent(limit=limit)

    async def get_quality_gate(self, task_id: UUID) -> QualityGateResult:
        try:
            latest_run = await self._agent_runs.get_latest_run_for_task(task_id)
        except OrchestratorTaskNotFoundError as exc:
            raise TaskNotFoundError(task_id) from exc

        if latest_run is None:
            return QualityGateResult(task_id=task_id, agent_run_id=None, overall="pending", evaluations=[])

        evaluations = await self._evaluations.list_for_agent_run(latest_run.id)
        summaries = []
        all_results: list[EvaluationResult] = []
        for evaluation in evaluations:
            results = await self._results.list_for_evaluation(evaluation.id)
            all_results.extend(results)
            summaries.append(
                QualityGateEvaluationSummary(
                    evaluator_type=evaluation.evaluator_type,
                    status=evaluation.status,
                    results=results,
                )
            )

        # docs/architecture/07-evaluation-framework.md §7's aggregation formula, in its own
        # priority order: pending beats failed beats passed.
        overall: Literal["passed", "failed", "pending"]
        if not evaluations or any(e.status.value in _PENDING_STATUSES for e in evaluations):
            overall = "pending"
        elif any(e.status.value in ("failed", "error") for e in evaluations) or any(
            not r.passed for r in all_results
        ):
            overall = "failed"
        else:
            overall = "passed"

        return QualityGateResult(
            task_id=task_id, agent_run_id=latest_run.id, overall=overall, evaluations=summaries
        )
