"""Maps a registered `agents` row's `agent_type` to a live `BaseAgent` instance to run.

A real deployment would register one concrete `BaseAgent` subclass per real agent implementation
(e.g. `DocumentationAgent` backed by a real `ModelProvider`) here instead of `EchoAgent` — see
`reference_agent.py`'s module docstring for why this reference implementation doesn't.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from aep_agent_sdk import AgentType, BaseAgent, EventPublisher

from .reference_agent import make_echo_agent_class

AgentFactory = Callable[..., BaseAgent]


class AgentRegistry:
    """An injectable `{AgentType: factory}` map — swappable per deployment, defaulting to
    `EchoAgent` for every type."""

    def __init__(self, factories: dict[AgentType, AgentFactory] | None = None) -> None:
        self._factories = factories or self._default_factories()

    @staticmethod
    def _default_factories() -> dict[AgentType, AgentFactory]:
        def make_factory(agent_type: AgentType) -> AgentFactory:
            agent_class = make_echo_agent_class(agent_type)

            def factory(
                *,
                agent_id: UUID,
                version: str,
                config: dict[str, Any] | None,
                event_publisher: EventPublisher | None,
            ) -> BaseAgent:
                return agent_class(
                    agent_id=agent_id,
                    version=version,
                    config=config,
                    event_publisher=event_publisher,
                )

            return factory

        return {agent_type: make_factory(agent_type) for agent_type in AgentType}

    def create(
        self,
        agent_type: AgentType,
        *,
        agent_id: UUID,
        version: str,
        config: dict[str, Any] | None = None,
        event_publisher: EventPublisher | None = None,
    ) -> BaseAgent:
        factory = self._factories[agent_type]
        return factory(
            agent_id=agent_id, version=version, config=config, event_publisher=event_publisher
        )
