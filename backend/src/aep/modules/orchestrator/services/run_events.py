"""In-memory pub/sub backing `GET /agent-runs/{runId}/events` (docs/architecture/04-api-design.md
§5.6's Server-Sent Events stream).

`core.events.RedisEventPublisher` is what the architecture actually intends for this (its own
docstring names this exact SSE stream as "the current consumer"), but no Redis server is
available in this dev/test environment to build/test against for real — so, following
`core.events.InMemoryEventPublisher`'s own precedent ("for local dev and tests where a Redis
instance isn't available"), this is a real (not mocked) in-memory broker for the same purpose,
scoped per `agent_run_id` rather than one shared channel. A real deployment with Redis available
should subscribe to `RedisEventPublisher`'s channel here instead.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any
from uuid import UUID

# `agent_run.persisted` (published by `agent_run_service._execute_and_persist()` after its own DB
# commit, not by the SDK) is what actually ends a stream — see that function's docstring. The
# SDK's own `agent_run.completed`/`failed`/`cancelled` events still flow through beforehand, just
# aren't what `subscribe()` stops on, since they fire before the row is guaranteed persisted.
_TERMINAL_EVENT_TYPES = frozenset({"agent_run.persisted"})


class RunEventBroker:
    """One `asyncio.Queue` per currently-subscribed `agent_run_id`, plus a per-run history buffer
    replayed to every new subscriber before it starts waiting on the live queue.

    The history buffer isn't a nice-to-have: `EchoAgent` (this module's reference agent) with no
    configured delay runs its entire `plan -> execute -> evaluate -> report` lifecycle — and
    publishes every one of its events, including the terminal one — in well under a millisecond,
    almost always *before* a client's `GET .../events` request has even been scheduled by the
    event loop. A pure fire-and-forget broker (`RedisEventPublisher`'s own Pub/Sub semantics, and
    this class's first draft) drops every one of those events on the floor, and a subscriber that
    attaches after they're gone waits forever for an event that already happened. Buffering and
    replaying is this module's honest equivalent of `RedisEventPublisher`'s own docstring
    admitting Redis Streams would be needed for a consumer requiring at-least-once delivery — this
    reference implementation turned out to be exactly that consumer once a real (near-instant)
    agent exposed the gap, not a hypothetical one.

    Replay is race-free without extra locking: `subscribe()` registers the live queue and reads
    the history snapshot back-to-back with no `await` in between, and `publish()` only ever runs
    on the same event loop — asyncio's cooperative scheduling means no `publish()` call can
    interleave between those two lines, so every event lands in the history snapshot, the queue,
    or both in a way `subscribe()`'s replay-then-drain order accounts for, but never neither.

    History is retained for the process's lifetime rather than pruned after a run settles — an
    acceptable memory/dev-only tradeoff (a handful of small dict events per run) for a reference
    implementation; a real Redis Streams-backed version would have its own retention/trimming
    policy instead of relying on this.
    """

    def __init__(self) -> None:
        self._subscribers: dict[UUID, list[asyncio.Queue[tuple[str, dict[str, Any]]]]] = {}
        self._history: dict[UUID, list[tuple[str, dict[str, Any]]]] = {}

    async def publish(self, agent_run_id: UUID, event_type: str, payload: dict[str, Any]) -> None:
        self._history.setdefault(agent_run_id, []).append((event_type, payload))
        for queue in self._subscribers.get(agent_run_id, []):
            queue.put_nowait((event_type, payload))

    async def subscribe(self, agent_run_id: UUID) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._subscribers.setdefault(agent_run_id, []).append(queue)
        history_snapshot = list(self._history.get(agent_run_id, []))
        try:
            for event_type, payload in history_snapshot:
                yield event_type, payload
                if event_type in _TERMINAL_EVENT_TYPES:
                    return
            while True:
                event_type, payload = await queue.get()
                yield event_type, payload
                if event_type in _TERMINAL_EVENT_TYPES:
                    return
        finally:
            self._subscribers[agent_run_id].remove(queue)
            if not self._subscribers[agent_run_id]:
                del self._subscribers[agent_run_id]


class RunEventPublisherAdapter:
    """Satisfies the `EventPublisher` protocol independently declared in `aep_agent_sdk`, routing
    each published event to `RunEventBroker` by the `agent_run_id` `BaseAgent._publish()` already
    embeds in every event's payload — one adapter instance per run, handed to `BaseAgent` as its
    `event_publisher`."""

    def __init__(self, broker: RunEventBroker, agent_run_id: UUID) -> None:
        self._broker = broker
        self._agent_run_id = agent_run_id

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        await self._broker.publish(self._agent_run_id, event_type, payload)


@lru_cache
def get_run_event_broker() -> RunEventBroker:
    """A process-wide singleton — every request's `AgentRunService` shares the same broker so a
    run started by one request can be subscribed to (cancelled, streamed) by another."""
    return RunEventBroker()
