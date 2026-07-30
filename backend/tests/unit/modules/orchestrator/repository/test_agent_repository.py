from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.orchestrator.domain.models import Agent, AgentType
from aep.modules.orchestrator.repository.agent_repository import AgentRepository


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
        yield AgentRepository(session)


async def test_add_and_get_by_id_round_trips(repository: AgentRepository) -> None:
    agent = Agent(
        id=uuid4(),
        name="CodingAgent",
        agent_type=AgentType.CODING,
        version="1.0.0",
        config={"foo": "bar"},
    )

    created = await repository.add(agent)
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.name == "CodingAgent"
    assert fetched.agent_type == AgentType.CODING
    assert fetched.config == {"foo": "bar"}


async def test_get_by_name_and_version(repository: AgentRepository) -> None:
    await repository.add(
        Agent(id=uuid4(), name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")
    )

    found = await repository.get_by_name_and_version("CodingAgent", "1.0.0")
    missing = await repository.get_by_name_and_version("CodingAgent", "2.0.0")

    assert found is not None
    assert missing is None


async def test_list_filters_by_type_and_enabled(repository: AgentRepository) -> None:
    coding = await repository.add(
        Agent(id=uuid4(), name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")
    )
    await repository.add(
        Agent(
            id=uuid4(),
            name="TestingAgent",
            agent_type=AgentType.TESTING,
            version="1.0.0",
            is_enabled=False,
        )
    )

    coding_only, coding_total = await repository.list(agent_type=AgentType.CODING)
    _enabled_only, enabled_total = await repository.list(is_enabled=True)

    assert coding_total == 1
    assert coding_only[0].id == coding.id
    assert enabled_total == 1


async def test_update_persists_enabled_and_config(repository: AgentRepository) -> None:
    agent = await repository.add(
        Agent(id=uuid4(), name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")
    )

    agent.is_enabled = False
    agent.config = {"execution_delay_seconds": 1.0}
    updated = await repository.update(agent)

    assert updated.is_enabled is False
    assert updated.config == {"execution_delay_seconds": 1.0}
