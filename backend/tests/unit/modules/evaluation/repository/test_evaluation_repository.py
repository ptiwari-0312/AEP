from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.evaluation.domain.models import (
    Evaluation,
    EvaluationStatus,
    EvaluatorType,
)
from aep.modules.evaluation.repository.evaluation_repository import EvaluationRepository


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
async def repository():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield EvaluationRepository(session)


async def test_add_and_get_by_id_round_trips(repository: EvaluationRepository) -> None:
    agent_run_id = uuid4()
    evaluation = Evaluation(
        id=uuid4(),
        agent_run_id=agent_run_id,
        evaluator_type=EvaluatorType.PERFORMANCE,
        status=EvaluationStatus.PASSED,
    )

    created = await repository.add(evaluation)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.agent_run_id == agent_run_id
    assert fetched.evaluator_type == EvaluatorType.PERFORMANCE
    assert fetched.status == EvaluationStatus.PASSED


async def test_get_by_id_returns_none_when_missing(repository: EvaluationRepository) -> None:
    assert await repository.get_by_id(uuid4()) is None


async def test_list_for_agent_run_scopes_and_orders_by_created_at(
    repository: EvaluationRepository,
) -> None:
    agent_run_id = uuid4()
    other_run_id = uuid4()
    first = await repository.add(
        Evaluation(id=uuid4(), agent_run_id=agent_run_id, evaluator_type=EvaluatorType.PERFORMANCE)
    )
    second = await repository.add(
        Evaluation(id=uuid4(), agent_run_id=agent_run_id, evaluator_type=EvaluatorType.LLM_JUDGE)
    )
    await repository.add(
        Evaluation(id=uuid4(), agent_run_id=other_run_id, evaluator_type=EvaluatorType.UNIT_TEST)
    )

    results = await repository.list_for_agent_run(agent_run_id)

    assert [e.id for e in results] == [first.id, second.id]
