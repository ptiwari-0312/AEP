"""AEP Evaluation SDK — the plugin interface every quality-gate evaluator implements.

See docs/architecture/07-evaluation-framework.md for the full design rationale.
"""

from .base import BaseEvaluator
from .runtime import EventPublisher, MetricsSink, NullEventPublisher, NullMetricsSink
from .types import (
    AgentRunArtifact,
    AgentRunContext,
    EvaluationReport,
    EvaluationStatus,
    EvaluatorCategory,
    EvaluatorInput,
    EvaluatorOutput,
    EvaluatorOutputStatus,
    EvaluatorType,
    MetricScore,
    category_of,
)

__all__ = [
    "AgentRunArtifact",
    "AgentRunContext",
    "BaseEvaluator",
    "EvaluationReport",
    "EvaluationStatus",
    "EvaluatorCategory",
    "EvaluatorInput",
    "EvaluatorOutput",
    "EvaluatorOutputStatus",
    "EvaluatorType",
    "EventPublisher",
    "MetricScore",
    "MetricsSink",
    "NullEventPublisher",
    "NullMetricsSink",
    "category_of",
]
