from __future__ import annotations

from uuid import uuid4

from aep.modules.metrics.domain.models import (
    Metric,
    MetricSummary,
    ProjectMetricsSummary,
)


def test_metric_defaults() -> None:
    metric = Metric(
        id=uuid4(), metric_name="agent_run.cost_usd", entity_type="agent_run", entity_id=uuid4(), value=0.05
    )

    assert metric.unit is None
    assert metric.recorded_at is None


def test_metric_summary_defaults_to_empty_buckets() -> None:
    summary = MetricSummary(metric_name="agent_run.cost_usd", group_by="day", agg="sum")

    assert summary.buckets == []


def test_project_metrics_summary_defaults_to_empty_metrics() -> None:
    summary = ProjectMetricsSummary(project_id=uuid4())

    assert summary.metrics == []
