"""Ports the host (AEP's Evaluation Runner) implements to wire an evaluator into real event/
metrics infrastructure, without this SDK depending on that infrastructure. Deliberately not
shared with aep-agent-sdk's equivalent module — each sdk/* package is independently installable
and depends on nothing under backend/ or on a sibling SDK (docs/architecture/02-repo-design.md §9)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EventPublisher(Protocol):
    """Publishes one evaluation lifecycle event."""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...


@runtime_checkable
class MetricsSink(Protocol):
    """Records one metric point."""

    def emit(self, metric_name: str, value: float, **tags: Any) -> None: ...


class NullEventPublisher:
    """No-op default so a BaseEvaluator is constructible and testable standalone, with no host
    wired in."""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


class NullMetricsSink:
    """No-op default so a BaseEvaluator is constructible and testable standalone, with no host
    wired in."""

    def emit(self, metric_name: str, value: float, **tags: Any) -> None:
        return None
