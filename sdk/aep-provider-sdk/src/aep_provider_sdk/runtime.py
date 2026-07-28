"""Ports the host (AEP's Agent Orchestrator / Context Builder) implements to wire a provider
into real event/metrics infrastructure, without this SDK depending on that infrastructure.
Deliberately not shared with aep-agent-sdk/aep-eval-sdk's equivalent modules — each sdk/*
package is independently installable and depends on nothing under backend/ or a sibling SDK
(docs/architecture/02-repo-design.md §9)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventPublisher(Protocol):
    """Publishes one provider-call lifecycle event."""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...


@runtime_checkable
class MetricsSink(Protocol):
    """Records one metric point."""

    def emit(self, metric_name: str, value: float, **tags: Any) -> None: ...


class NullEventPublisher:
    """No-op default so a ModelProvider is constructible and testable standalone, with no host
    wired in."""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


class NullMetricsSink:
    """No-op default so a ModelProvider is constructible and testable standalone, with no host
    wired in."""

    def emit(self, metric_name: str, value: float, **tags: Any) -> None:
        return None
