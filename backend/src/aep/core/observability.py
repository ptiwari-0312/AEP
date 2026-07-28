"""Structured logging, OpenTelemetry tracing setup, and the MetricsSink implementation
(docs/architecture/09-engineering-standards.md §5; docs/architecture/01-vision-and-principles.md
§7's observability principle).

The MetricsSink implemented here records onto OpenTelemetry instruments — genuinely
core-appropriate, since it requires no dependency on any module's database schema. Persisting
metric points into the `metrics` table for the Dashboard's Metrics screen
(docs/architecture/03-db-design.md §18) is deliberately NOT done here: that's the Metrics
Service module's job (`modules/metrics/`), which doesn't exist yet. When it does, it should
derive its rows from this same event/metrics stream (per ADR-004), not duplicate emission logic
— `core/` must stay free of module-specific persistence (docs/architecture/02-repo-design.md §2:
"nothing under modules/" may be a dependency of `core/`).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from opentelemetry import metrics as otel_metrics
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SpanProcessor,
)

from .config import Settings, get_settings


@runtime_checkable
class MetricsSink(Protocol):
    def emit(self, metric_name: str, value: float, **tags: Any) -> None: ...


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(settings: Settings | None = None) -> None:
    """Human-readable in development, structured JSON otherwise
    (docs/architecture/09-engineering-standards.md §5) — never `print()`."""
    settings = settings or get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        if settings.environment == "development"
        else _JsonLogFormatter()
    )
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))


def configure_tracing(
    settings: Settings | None = None, *, span_processor: SpanProcessor | None = None
) -> TracerProvider:
    """Sets the global TracerProvider. Defaults to a console exporter (visible locally with no
    external infra); pass `span_processor` to inject a test double (e.g. a `SimpleSpanProcessor`
    wrapping an `InMemorySpanExporter`) instead of relying on global OTel state in tests."""
    settings = settings or get_settings()
    provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
    provider.add_span_processor(span_processor or BatchSpanProcessor(ConsoleSpanExporter()))
    otel_trace.set_tracer_provider(provider)
    return provider


def configure_metrics(
    settings: Settings | None = None, *, metric_reader: MetricReader | None = None
) -> MeterProvider:
    """Sets the global MeterProvider. Defaults to a periodic console exporter; pass
    `metric_reader` to inject an `InMemoryMetricReader` in tests instead."""
    settings = settings or get_settings()
    reader = metric_reader or PeriodicExportingMetricReader(ConsoleMetricExporter())
    provider = MeterProvider(
        resource=Resource.create({"service.name": settings.otel_service_name}),
        metric_readers=[reader],
    )
    otel_metrics.set_meter_provider(provider)
    return provider


class OpenTelemetryMetricsSink:
    """Satisfies the `MetricsSink` protocol independently declared in each of sdk/aep-agent-sdk,
    sdk/aep-eval-sdk, and sdk/aep-provider-sdk, via structural typing — same mechanism as
    `events.py`'s `RedisEventPublisher`.

    Every metric is recorded as a histogram observation, uniformly, rather than picking
    Counter/Histogram/Gauge per metric name: `emit()`'s flat `(name, value, **tags)` signature
    doesn't carry enough metadata to choose correctly per call site, and a histogram can
    represent any of duration/token-count/cost/pass-fail(0-or-1) reasonably, whereas a
    monotonic Counter cannot represent a pass/fail flag at all.
    """

    def __init__(self, meter: otel_metrics.Meter | None = None) -> None:
        self._meter = meter or otel_metrics.get_meter("aep")
        self._instruments: dict[str, otel_metrics.Histogram] = {}

    def emit(self, metric_name: str, value: float, **tags: Any) -> None:
        histogram = self._instruments.get(metric_name)
        if histogram is None:
            histogram = self._meter.create_histogram(metric_name.replace(".", "_"))
            self._instruments[metric_name] = histogram
        histogram.record(value, attributes={key: str(val) for key, val in tags.items()})
