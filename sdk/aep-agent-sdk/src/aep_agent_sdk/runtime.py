"""Ports the host (AEP's Agent Orchestrator) implements to wire an agent into real event/metrics
infrastructure, without this SDK depending on that infrastructure — sdk/* has zero dependency on
backend/ (docs/architecture/02-repo-design.md §9)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventPublisher(Protocol):
    """Publishes one lifecycle domain event (docs/architecture/05-agent-sdk.md §12)."""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...


@runtime_checkable
class MetricsSink(Protocol):
    """Records one metric point (docs/architecture/05-agent-sdk.md §10)."""

    def emit(self, metric_name: str, value: float, **tags: Any) -> None: ...


class NullEventPublisher:
    """No-op default so a BaseAgent is constructible and testable standalone, with no host
    wired in."""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


class NullMetricsSink:
    """No-op default so a BaseAgent is constructible and testable standalone, with no host
    wired in."""

    def emit(self, metric_name: str, value: float, **tags: Any) -> None:
        return None
