"""Data access for `agents` (docs/architecture/03-db-design.md §8)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.models import Agent, AgentType
from .models import AgentModel


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, agent: Agent) -> Agent:
        model = _to_model(agent)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def get_by_id(self, agent_id: UUID) -> Agent | None:
        model = await self._session.get(AgentModel, agent_id)
        return _to_domain(model) if model else None

    async def get_by_name_and_version(self, name: str, version: str) -> Agent | None:
        result = await self._session.execute(
            select(AgentModel).where(AgentModel.name == name, AgentModel.version == version)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model else None

    async def list(
        self,
        *,
        agent_type: AgentType | None = None,
        is_enabled: bool | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Agent], int]:
        query = select(AgentModel)
        count_query = select(func.count()).select_from(AgentModel)
        if agent_type is not None:
            query = query.where(AgentModel.agent_type == agent_type.value)
            count_query = count_query.where(AgentModel.agent_type == agent_type.value)
        if is_enabled is not None:
            query = query.where(AgentModel.is_enabled == is_enabled)
            count_query = count_query.where(AgentModel.is_enabled == is_enabled)

        total = (await self._session.execute(count_query)).scalar_one()

        query = query.order_by(AgentModel.created_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [_to_domain(m) for m in result.scalars().all()], total

    async def update(self, agent: Agent) -> Agent:
        model = await self._session.get(AgentModel, agent.id)
        if model is None:
            raise ValueError(f"agent {agent.id} does not exist — call add() first")
        model.is_enabled = agent.is_enabled
        model.config = agent.config
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)


def _to_domain(model: AgentModel) -> Agent:
    return Agent(
        id=model.id,
        name=model.name,
        agent_type=AgentType(model.agent_type),
        version=model.version,
        is_enabled=model.is_enabled,
        config=dict(model.config),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_model(agent: Agent) -> AgentModel:
    return AgentModel(
        id=agent.id,
        name=agent.name,
        agent_type=agent.agent_type.value,
        version=agent.version,
        is_enabled=agent.is_enabled,
        config=dict(agent.config),
    )
