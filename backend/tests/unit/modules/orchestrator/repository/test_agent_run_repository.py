from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory, utcnow
from aep.modules.orchestrator.domain.models import (
    Agent,
    AgentRun,
    AgentRunStatus,
    AgentType,
)
from aep.modules.orchestrator.repository.agent_repository import AgentRepository
from aep.modules.orchestrator.repository.agent_run_repository import AgentRunRepository


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
async def repository(session):
    return AgentRunRepository(session)


@pytest.fixture
async def agent_id(session):
    agent = await AgentRepository(session).add(
        Agent(id=uuid4(), name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")
    )
    return agent.id


async def test_add_and_get_by_id_round_trips(repository: AgentRunRepository, agent_id) -> None:
    task_id = uuid4()
    run = AgentRun(
        id=uuid4(), agent_id=agent_id, task_id=task_id, provider="claude", model_name="claude-x"
    )

    created = await repository.add(run)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.task_id == task_id
    assert fetched.status == AgentRunStatus.QUEUED


async def test_list_for_task_scopes_and_paginates_with_cursor(
    repository: AgentRunRepository, agent_id
) -> None:
    task_id = uuid4()
    other_task_id = uuid4()
    for _ in range(3):
        await repository.add(
            AgentRun(
                id=uuid4(),
                agent_id=agent_id,
                task_id=task_id,
                provider="claude",
                model_name="claude-x",
            )
        )
    await repository.add(
        AgentRun(
            id=uuid4(),
            agent_id=agent_id,
            task_id=other_task_id,
            provider="claude",
            model_name="claude-x",
        )
    )

    first_page, cursor, has_more = await repository.list_for_task(task_id, limit=2)
    assert len(first_page) == 2
    assert has_more is True
    assert cursor is not None

    second_page, cursor2, has_more2 = await repository.list_for_task(
        task_id, limit=2, cursor=cursor
    )
    assert len(second_page) == 1
    assert has_more2 is False
    assert cursor2 is None


async def test_update_persists_status_and_completion_fields(
    repository: AgentRunRepository, agent_id
) -> None:
    run = await repository.add(
        AgentRun(
            id=uuid4(), agent_id=agent_id, task_id=uuid4(), provider="claude", model_name="claude-x"
        )
    )

    run.status = AgentRunStatus.SUCCEEDED
    run.completed_at = utcnow()
    run.input_tokens = 10
    run.output_tokens = 20
    run.cost_usd = 0.05
    updated = await repository.update(run)

    assert updated.status == AgentRunStatus.SUCCEEDED
    assert updated.input_tokens == 10
    assert updated.output_tokens == 20
    assert updated.cost_usd == 0.05
    assert updated.completed_at is not None


async def test_count_and_list_by_statuses_are_global_not_scoped_to_a_task(
    repository: AgentRunRepository, agent_id
) -> None:
    running = await repository.add(
        AgentRun(
            id=uuid4(), agent_id=agent_id, task_id=uuid4(), provider="claude", model_name="claude-x",
            status=AgentRunStatus.RUNNING,
        )
    )
    await repository.add(
        AgentRun(
            id=uuid4(), agent_id=agent_id, task_id=uuid4(), provider="claude", model_name="claude-x",
            status=AgentRunStatus.SUCCEEDED,
        )
    )

    count = await repository.count_by_statuses([AgentRunStatus.RUNNING, AgentRunStatus.RETRYING])
    listed = await repository.list_by_statuses([AgentRunStatus.RUNNING, AgentRunStatus.RETRYING])

    assert count == 1
    assert [r.id for r in listed] == [running.id]
