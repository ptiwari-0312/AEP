"""Data access for `evaluations` (docs/architecture/03-db-design.md §14)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Evaluation, EvaluationStatus, EvaluatorType
from .models import EvaluationModel


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, evaluation: Evaluation) -> Evaluation:
        model = _to_model(evaluation)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, evaluation_id: UUID) -> Evaluation | None:
        model = await self._session.get(EvaluationModel, evaluation_id)
        return _to_domain(model) if model else None

    async def list_for_agent_run(self, agent_run_id: UUID) -> list[Evaluation]:
        # Bounded by design: at most one row per evaluator type (12 total), so a plain list
        # rather than a paginated envelope — same precedent as `projects`' feature listing.
        result = await self._session.execute(
            select(EvaluationModel)
            .where(EvaluationModel.agent_run_id == agent_run_id)
            .order_by(EvaluationModel.created_at.asc())
        )
        return [_to_domain(m) for m in result.scalars().all()]

    async def list_recent(self, *, limit: int = 10) -> list[Evaluation]:
        """Global listing across every agent run, newest first — added while building
        `dashboard_api`, whose overview read-model needs "recent evaluations" system-wide, not
        scoped to one run like `list_for_agent_run()`."""
        result = await self._session.execute(
            select(EvaluationModel).order_by(EvaluationModel.created_at.desc()).limit(limit)
        )
        return [_to_domain(m) for m in result.scalars().all()]


def _to_domain(model: EvaluationModel) -> Evaluation:
    return Evaluation(
        id=model.id,
        agent_run_id=model.agent_run_id,
        evaluator_type=EvaluatorType(model.evaluator_type),
        status=EvaluationStatus(model.status),
        started_at=model.started_at,
        completed_at=model.completed_at,
        created_at=model.created_at,
    )


def _to_model(evaluation: Evaluation) -> EvaluationModel:
    return EvaluationModel(
        id=evaluation.id,
        agent_run_id=evaluation.agent_run_id,
        evaluator_type=evaluation.evaluator_type.value,
        status=evaluation.status.value,
        started_at=evaluation.started_at,
        completed_at=evaluation.completed_at,
    )
