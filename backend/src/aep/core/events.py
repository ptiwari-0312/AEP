"""Domain event bus (ADR-004, docs/architecture/01-vision-and-principles.md).

This is the concrete implementation satisfying the `EventPublisher` protocol independently
declared in each of sdk/aep-agent-sdk, sdk/aep-eval-sdk, and sdk/aep-provider-sdk. Because each
SDK declares its own `Protocol` rather than importing a shared base class
(docs/architecture/02-repo-design.md §9 — sdk/* depends on nothing under backend/), a single
class here satisfies all three simultaneously through structural typing, without this module
importing any of them.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

import redis.asyncio as redis

logger = logging.getLogger("aep.events")

DEFAULT_CHANNEL = "aep:events"


@runtime_checkable
class EventPublisher(Protocol):
    async def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...


class RedisEventPublisher:
    """Publishes onto a single Redis Pub/Sub channel as a `{"event_type", "payload"}` envelope.

    Redis Pub/Sub is fire-and-forget — no persistence, no replay, delivered only to subscribers
    connected at publish time. That's sufficient for the current consumer (a live SSE stream
    reading agent-run/evaluation events, docs/architecture/04-api-design.md §5.6) but would not
    be for a consumer needing at-least-once delivery (e.g. a future Audit Event writer that must
    not silently miss an event). If that need arises, this should move to Redis Streams — not
    be quietly relied upon to already provide it.
    """

    def __init__(self, client: redis.Redis, *, channel: str = DEFAULT_CHANNEL) -> None:
        self._client = client
        self._channel = channel

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope = json.dumps({"event_type": event_type, "payload": payload}, default=str)
        await self._client.publish(self._channel, envelope)


class InMemoryEventPublisher:
    """Records events in-process instead of publishing anywhere — for local dev and tests where
    a Redis instance isn't available or isn't the point of the test."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))
        logger.debug("event published: %s %s", event_type, payload)
