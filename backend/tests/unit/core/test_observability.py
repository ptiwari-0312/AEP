from __future__ import annotations

import json
import logging

import pytest
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aep.core.config import Settings
from aep.core.observability import (
    MetricsSink,
    OpenTelemetryMetricsSink,
    _JsonLogFormatter,
    configure_logging,
    configure_metrics,
    configure_tracing,
)


def test_json_formatter_produces_valid_json_with_expected_fields() -> None:
    formatter = _JsonLogFormatter()
    record = logging.LogRecord(
        name="aep.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )

    formatted = json.loads(formatter.format(record))

    assert formatted["level"] == "INFO"
    assert formatted["module"] == "aep.test"
    assert formatted["message"] == "hello world"
    assert "timestamp" in formatted


def test_configure_logging_uses_json_formatter_outside_development() -> None:
    configure_logging(Settings(environment="production", _env_file=None))
    root_logger = logging.getLogger()

    assert isinstance(root_logger.handlers[0].formatter, _JsonLogFormatter)


def test_configure_logging_uses_plain_formatter_in_development() -> None:
    configure_logging(Settings(environment="development", _env_file=None))
    root_logger = logging.getLogger()

    assert not isinstance(root_logger.handlers[0].formatter, _JsonLogFormatter)


def test_configure_tracing_records_spans_via_injected_processor() -> None:
    exporter = InMemorySpanExporter()
    provider = configure_tracing(
        Settings(_env_file=None), span_processor=SimpleSpanProcessor(exporter)
    )
    assert isinstance(provider, TracerProvider)

    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("do-a-thing"):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "do-a-thing"


def test_configure_metrics_returns_a_meter_provider_using_injected_reader() -> None:
    reader = InMemoryMetricReader()
    provider = configure_metrics(Settings(_env_file=None), metric_reader=reader)

    assert isinstance(provider, MeterProvider)


def test_open_telemetry_metrics_sink_records_histogram_observation() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    sink = OpenTelemetryMetricsSink(meter=provider.get_meter("test"))

    sink.emit("agent_run.duration_ms", 123.0, agent_type="coding")

    data = reader.get_metrics_data()
    resource_metrics = data.resource_metrics
    assert len(resource_metrics) == 1
    metric = resource_metrics[0].scope_metrics[0].metrics[0]
    assert metric.name == "agent_run_duration_ms"
    data_point = metric.data.data_points[0]
    assert data_point.sum == 123.0
    assert dict(data_point.attributes) == {"agent_type": "coding"}


def test_open_telemetry_metrics_sink_reuses_the_same_instrument_across_calls() -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    sink = OpenTelemetryMetricsSink(meter=provider.get_meter("test"))

    sink.emit("agent_run.cost_usd", 0.01)
    sink.emit("agent_run.cost_usd", 0.02)

    data_point = reader.get_metrics_data().resource_metrics[0].scope_metrics[0].metrics[0].data.data_points[0]
    assert data_point.count == 2
    assert data_point.sum == pytest.approx(0.03)


def test_satisfies_agent_sdk_and_eval_sdk_and_provider_sdk_metrics_sink_protocols() -> None:
    from aep_agent_sdk import MetricsSink as AgentMetricsSink
    from aep_eval_sdk import MetricsSink as EvalMetricsSink
    from aep_provider_sdk import MetricsSink as ProviderMetricsSink

    sink = OpenTelemetryMetricsSink(meter=MeterProvider().get_meter("test"))
    assert isinstance(sink, MetricsSink)
    assert isinstance(sink, AgentMetricsSink)
    assert isinstance(sink, EvalMetricsSink)
    assert isinstance(sink, ProviderMetricsSink)
