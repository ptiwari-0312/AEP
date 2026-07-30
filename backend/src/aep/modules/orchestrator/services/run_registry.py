"""Tracks in-flight agent runs so `POST /agent-runs/{runId}/cancel` can reach the live agent
instance actually executing it.

A real deployment would run agents in a separate worker process behind a distributed queue
(the architecture docs mention Redis for exactly this kind of cross-process coordination), where
"which process is running this run" is itself something to look up. This module runs agents
as in-process `asyncio` background tasks instead (the same "no distributed job runner exists in
`backend/` yet" stance `context_builder` takes for its own synchronous generation), so a plain
in-memory dict keyed by `agent_run_id`, scoped to this one process, is the honest equivalent —
not a fake, just a smaller deployment topology.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

from aep_agent_sdk import BaseAgent


@dataclass
class _ActiveRun:
    task: asyncio.Task[None]
    agent: BaseAgent


class RunRegistry:
    def __init__(self) -> None:
        self._active: dict[UUID, _ActiveRun] = {}

    def track(self, agent_run_id: UUID, task: asyncio.Task[None], agent: BaseAgent) -> None:
        self._active[agent_run_id] = _ActiveRun(task=task, agent=agent)

    def untrack(self, agent_run_id: UUID) -> None:
        self._active.pop(agent_run_id, None)

    def is_active(self, agent_run_id: UUID) -> bool:
        return agent_run_id in self._active

    async def cancel(self, agent_run_id: UUID) -> bool:
        """Requests cooperative cancellation on the live agent instance, if one is tracked for
        this run. Returns whether a live instance was found — cancellation itself is
        asynchronous: the run settles (and untracks itself) once the agent's `execute()` next
        observes the cancellation token, not immediately."""
        active = self._active.get(agent_run_id)
        if active is None:
            return False
        await active.agent.cancel()
        return True

    async def wait_for(self, agent_run_id: UUID) -> None:
        """Awaits the tracked background task's completion — lets tests observe a run's final
        persisted state deterministically instead of polling/sleeping. A no-op if the run isn't
        (or is no longer) tracked."""
        active = self._active.get(agent_run_id)
        if active is None:
            return
        with contextlib.suppress(asyncio.CancelledError):
            await active.task


@lru_cache
def get_run_registry() -> RunRegistry:
    """A process-wide singleton — every request's `AgentRunService` shares the same registry so
    a run started by one request can be cancelled/awaited by another, same rationale as
    `run_events.get_run_event_broker()`."""
    return RunRegistry()
