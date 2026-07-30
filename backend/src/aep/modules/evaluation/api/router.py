"""FastAPI routers for the Evaluation Framework (docs/architecture/04-api-design.md §7). Domain
exceptions are translated into `core/errors.py`'s HTTP-mapped `AEPError` subclasses here — the
sole boundary where that translation happens (docs/architecture/09-engineering-standards.md §6);
`domain/` and `services/` know nothing about HTTP.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from aep.core.errors import NotFoundError, ValidationFailedError

from ..domain.errors import (
    AgentRunNotFoundError,
    AgentRunNotSucceededError,
    EvaluationNotFoundError,
    EvaluatorTypeNotRegisteredError,
    TaskNotFoundError,
)
from ..services.evaluation_service import EvaluationService
from .dependencies import get_current_user_id, get_evaluation_service
from .schemas import (
    EvaluationResponse,
    EvaluationResultResponse,
    QualityGateEvaluationResponse,
    QualityGateResponse,
    TriggerEvaluationsRequest,
    TriggerEvaluationsResponse,
)

router = APIRouter(prefix="/api/v1", tags=["evaluation"])


@router.post(
    "/agent-runs/{run_id}/evaluations",
    response_model=TriggerEvaluationsResponse,
    status_code=202,
)
async def trigger_evaluations(
    run_id: UUID,
    request: TriggerEvaluationsRequest,
    service: EvaluationService = Depends(get_evaluation_service),
    _user_id: UUID = Depends(get_current_user_id),
) -> TriggerEvaluationsResponse:
    try:
        evaluations = await service.trigger_evaluations(
            run_id, evaluator_types=request.evaluator_types
        )
    except AgentRunNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    except AgentRunNotSucceededError as exc:
        raise ValidationFailedError(
            str(exc), errors=[{"field": "run_id", "message": "agent run has not succeeded yet"}]
        ) from exc
    except EvaluatorTypeNotRegisteredError as exc:
        raise ValidationFailedError(
            str(exc), errors=[{"field": "evaluator_types", "message": str(exc)}]
        ) from exc
    return TriggerEvaluationsResponse(evaluation_ids=[str(e.id) for e in evaluations])


@router.get("/agent-runs/{run_id}/evaluations", response_model=list[EvaluationResponse])
async def list_evaluations(
    run_id: UUID, service: EvaluationService = Depends(get_evaluation_service)
) -> list[EvaluationResponse]:
    try:
        evaluations = await service.list_evaluations_for_run(run_id)
    except AgentRunNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return [EvaluationResponse.model_validate(e) for e in evaluations]


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationResponse)
async def get_evaluation(
    evaluation_id: UUID, service: EvaluationService = Depends(get_evaluation_service)
) -> EvaluationResponse:
    try:
        evaluation = await service.get_evaluation(evaluation_id)
    except EvaluationNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return EvaluationResponse.model_validate(evaluation)


@router.get(
    "/evaluations/{evaluation_id}/results", response_model=list[EvaluationResultResponse]
)
async def list_results(
    evaluation_id: UUID, service: EvaluationService = Depends(get_evaluation_service)
) -> list[EvaluationResultResponse]:
    try:
        results = await service.list_results_for_evaluation(evaluation_id)
    except EvaluationNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return [EvaluationResultResponse.model_validate(r) for r in results]


@router.get("/tasks/{task_id}/quality-gate", response_model=QualityGateResponse)
async def get_quality_gate(
    task_id: UUID, service: EvaluationService = Depends(get_evaluation_service)
) -> QualityGateResponse:
    try:
        gate = await service.get_quality_gate(task_id)
    except TaskNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return QualityGateResponse(
        task_id=gate.task_id,
        agent_run_id=gate.agent_run_id,
        overall=gate.overall,
        evaluations=[
            QualityGateEvaluationResponse(
                evaluator_type=summary.evaluator_type,
                status=summary.status,
                results=[EvaluationResultResponse.model_validate(r) for r in summary.results],
            )
            for summary in gate.evaluations
        ],
    )
