"""Use-case orchestration for the `agents` catalog (docs/architecture/04-api-design.md §5)."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from ..domain.errors import AgentNameVersionExistsError, AgentNotFoundError
from ..domain.models import Agent, AgentType
from ..repository.agent_repository import AgentRepository


class AgentService:
    def __init__(self, agent_repository: AgentRepository) -> None:
        self._agents = agent_repository

    async def register_agent(
        self,
        *,
        name: str,
        agent_type: AgentType,
        version: str,
        config: dict[str, Any] | None = None,
    ) -> Agent:
        if await self._agents.get_by_name_and_version(name, version) is not None:
            raise AgentNameVersionExistsError(name, version)
        agent = Agent(
            id=uuid4(), name=name, agent_type=agent_type, version=version, config=config or {}
        )
        return await self._agents.add(agent)

    async def get_agent(self, agent_id: UUID) -> Agent:
        agent = await self._agents.get_by_id(agent_id)
        if agent is None:
            raise AgentNotFoundError(agent_id)
        return agent

    async def list_agents(
        self,
        *,
        agent_type: AgentType | None = None,
        is_enabled: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Agent], int]:
        return await self._agents.list(
            agent_type=agent_type, is_enabled=is_enabled, limit=limit, offset=offset
        )

    async def update_agent(
        self,
        agent_id: UUID,
        *,
        is_enabled: bool | None = None,
        config: dict[str, Any] | None = None,
    ) -> Agent:
        agent = await self.get_agent(agent_id)
        if is_enabled is not None:
            agent.is_enabled = is_enabled
        if config is not None:
            agent.config = config
        return await self._agents.update(agent)
