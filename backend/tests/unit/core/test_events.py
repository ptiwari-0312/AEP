from __future__ import annotations

import json
from typing import Any

from aep.core.events import EventPublisher, InMemoryEventPublisher, RedisEventPublisher


class _FakeRedisClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


async def test_redis_event_publisher_publishes_json_envelope_on_default_channel() -> None:
    fake_client = _FakeRedisClient()
    publisher = RedisEventPublisher(fake_client)  # type: ignore[arg-type]

    await publisher.publish("agent_run.completed", {"agent_run_id": "abc-123", "attempt_number": 1})

    assert len(fake_client.published) == 1
    channel, message = fake_client.published[0]
    assert channel == "aep:events"
    envelope: dict[str, Any] = json.loads(message)
    assert envelope["event_type"] == "agent_run.completed"
    assert envelope["payload"] == {"agent_run_id": "abc-123", "attempt_number": 1}


async def test_redis_event_publisher_respects_custom_channel() -> None:
    fake_client = _FakeRedisClient()
    publisher = RedisEventPublisher(fake_client, channel="aep:events:custom")  # type: ignore[arg-type]

    await publisher.publish("evaluation.completed", {})

    assert fake_client.published[0][0] == "aep:events:custom"


async def test_redis_event_publisher_serializes_non_json_native_values() -> None:
    from uuid import uuid4

    fake_client = _FakeRedisClient()
    publisher = RedisEventPublisher(fake_client)  # type: ignore[arg-type]

    await publisher.publish("agent_run.queued", {"agent_run_id": uuid4()})

    envelope = json.loads(fake_client.published[0][1])
    assert isinstance(envelope["payload"]["agent_run_id"], str)


async def test_in_memory_event_publisher_records_events() -> None:
    publisher = InMemoryEventPublisher()

    await publisher.publish("agent_run.completed", {"agent_run_id": "abc"})
    await publisher.publish("agent_run.failed", {"agent_run_id": "abc", "error": "boom"})

    assert publisher.events == [
        ("agent_run.completed", {"agent_run_id": "abc"}),
        ("agent_run.failed", {"agent_run_id": "abc", "error": "boom"}),
    ]


def test_redis_and_in_memory_publishers_satisfy_the_protocol() -> None:
    assert isinstance(InMemoryEventPublisher(), EventPublisher)
    assert isinstance(RedisEventPublisher(_FakeRedisClient()), EventPublisher)  # type: ignore[arg-type]


async def test_satisfies_agent_sdk_and_eval_sdk_and_provider_sdk_event_publisher_protocols() -> None:
    # The whole point of declaring EventPublisher as a structural Protocol independently in each
    # SDK (docs/architecture/02-repo-design.md §9) is that this single class should work
    # everywhere without any of those packages being imported here.
    from aep_agent_sdk import EventPublisher as AgentEventPublisher
    from aep_eval_sdk import EventPublisher as EvalEventPublisher
    from aep_provider_sdk import EventPublisher as ProviderEventPublisher

    publisher = InMemoryEventPublisher()
    assert isinstance(publisher, AgentEventPublisher)
    assert isinstance(publisher, EvalEventPublisher)
    assert isinstance(publisher, ProviderEventPublisher)
