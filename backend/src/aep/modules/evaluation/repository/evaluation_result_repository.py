"""Data access for `evaluation_results` (docs/architecture/03-db-design.md §15). Append-only —
no `update()`, matching the DB design's own note."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import EvaluationResult
from .models import EvaluationResultModel


class EvaluationResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, results: list[EvaluationResult]) -> list[EvaluationResult]:
        models = [_to_model(result) for result in results]
        self._session.add_all(models)
        await self._session.flush()
        for model in models:
            await self._session.refresh(model)
        return [_to_domain(m) for m in models]

    async def list_for_evaluation(self, evaluation_id: UUID) -> list[EvaluationResult]:
        result = await self._session.execute(
            select(EvaluationResultModel)
            .where(EvaluationResultModel.evaluation_id == evaluation_id)
            .order_by(EvaluationResultModel.created_at.asc())
        )
        return [_to_domain(m) for m in result.scalars().all()]


def _to_domain(model: EvaluationResultModel) -> EvaluationResult:
    return EvaluationResult(
        id=model.id,
        evaluation_id=model.evaluation_id,
        metric_name=model.metric_name,
        score=model.score,
        threshold=model.threshold,
        passed=model.passed,
        details=dict(model.details),
        created_at=model.created_at,
    )


def _to_model(result: EvaluationResult) -> EvaluationResultModel:
    return EvaluationResultModel(
        id=result.id,
        evaluation_id=result.evaluation_id,
        metric_name=result.metric_name,
        score=result.score,
        threshold=result.threshold,
        passed=result.passed,
        details=dict(result.details),
    )
