from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.orchestrator.domain.errors import (
    AgentNameVersionExistsError,
    AgentNotFoundError,
)
from aep.modules.orchestrator.domain.models import AgentType
from aep.modules.orchestrator.repository.agent_repository import AgentRepository
from aep.modules.orchestrator.services.agent_service import AgentService


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
async def service():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield AgentService(AgentRepository(session))


async def test_register_agent(service: AgentService) -> None:
    agent = await service.register_agent(
        name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0"
    )

    assert agent.name == "CodingAgent"
    assert agent.is_enabled is True


async def test_register_agent_rejects_duplicate_name_and_version(service: AgentService) -> None:
    await service.register_agent(name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")

    with pytest.raises(AgentNameVersionExistsError):
        await service.register_agent(
            name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0"
        )


async def test_register_agent_allows_same_name_different_version(service: AgentService) -> None:
    await service.register_agent(name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")
    v2 = await service.register_agent(
        name="CodingAgent", agent_type=AgentType.CODING, version="2.0.0"
    )

    assert v2.version == "2.0.0"


async def test_get_agent_raises_not_found(service: AgentService) -> None:
    with pytest.raises(AgentNotFoundError):
        await service.get_agent(uuid4())


async def test_update_agent_toggles_enabled_and_config(service: AgentService) -> None:
    agent = await service.register_agent(
        name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0"
    )

    updated = await service.update_agent(agent.id, is_enabled=False, config={"fail": True})

    assert updated.is_enabled is False
    assert updated.config == {"fail": True}


async def test_list_agents_filters(service: AgentService) -> None:
    await service.register_agent(name="CodingAgent", agent_type=AgentType.CODING, version="1.0.0")
    await service.register_agent(
        name="ReviewAgent", agent_type=AgentType.REVIEW, version="1.0.0"
    )

    coding_only, total = await service.list_agents(agent_type=AgentType.CODING)

    assert total == 1
    assert coding_only[0].agent_type == AgentType.CODING
