from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.evaluation.domain.models import (
    Evaluation,
    EvaluationResult,
    EvaluatorType,
)
from aep.modules.evaluation.repository.evaluation_repository import EvaluationRepository
from aep.modules.evaluation.repository.evaluation_result_repository import (
    EvaluationResultRepository,
)


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEP_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
async def evaluation(session) -> Evaluation:
    return await EvaluationRepository(session).add(
        Evaluation(id=uuid4(), agent_run_id=uuid4(), evaluator_type=EvaluatorType.PERFORMANCE)
    )


@pytest.fixture
def repository(session) -> EvaluationResultRepository:
    return EvaluationResultRepository(session)


async def test_add_many_and_list_for_evaluation(
    repository: EvaluationResultRepository, evaluation: Evaluation
) -> None:
    results = [
        EvaluationResult(
            id=uuid4(),
            evaluation_id=evaluation.id,
            metric_name="cost_usd",
            score=0.05,
            threshold=0.10,
            passed=True,
            details={"note": "under budget"},
        ),
        EvaluationResult(
            id=uuid4(),
            evaluation_id=evaluation.id,
            metric_name="duration_seconds",
            score=12.0,
            threshold=10.0,
            passed=False,
        ),
    ]

    await repository.add_many(results)
    fetched = await repository.list_for_evaluation(evaluation.id)

    assert len(fetched) == 2
    assert {r.metric_name for r in fetched} == {"cost_usd", "duration_seconds"}
    cost_result = next(r for r in fetched if r.metric_name == "cost_usd")
    assert cost_result.passed is True
    assert cost_result.details == {"note": "under budget"}


async def test_list_for_evaluation_scopes_by_evaluation_id(
    repository: EvaluationResultRepository, evaluation: Evaluation, session
) -> None:
    other_evaluation = await EvaluationRepository(session).add(
        Evaluation(id=uuid4(), agent_run_id=uuid4(), evaluator_type=EvaluatorType.LLM_JUDGE)
    )
    await repository.add_many(
        [
            EvaluationResult(
                id=uuid4(), evaluation_id=evaluation.id, metric_name="a", score=1.0, passed=True
            )
        ]
    )
    await repository.add_many(
        [
            EvaluationResult(
                id=uuid4(),
                evaluation_id=other_evaluation.id,
                metric_name="b",
                score=1.0,
                passed=True,
            )
        ]
    )

    only_this_evaluation = await repository.list_for_evaluation(evaluation.id)

    assert len(only_this_evaluation) == 1
    assert only_this_evaluation[0].metric_name == "a"
