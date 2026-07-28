"""AEP Agent SDK — the plugin interface every AI agent type implements.

See docs/architecture/05-agent-sdk.md for the full design rationale.
"""

from .base import BaseAgent
from .cancellation import CancellationToken
from .errors import (
    AgentCancelledError,
    AgentError,
    AgentTimeoutError,
    RetryableAgentError,
    TerminalAgentError,
)
from .retry import RetryPolicy
from .runtime import EventPublisher, MetricsSink, NullEventPublisher, NullMetricsSink
from .types import (
    AgentReport,
    AgentRunStatus,
    AgentType,
    ExecutionArtifact,
    ExecutionResult,
    HeartbeatSignal,
    Plan,
    PlanStep,
    SelfEvaluation,
    TaskContext,
)

__all__ = [
    "AgentCancelledError",
    "AgentError",
    "AgentReport",
    "AgentRunStatus",
    "AgentTimeoutError",
    "AgentType",
    "BaseAgent",
    "CancellationToken",
    "EventPublisher",
    "ExecutionArtifact",
    "ExecutionResult",
    "HeartbeatSignal",
    "MetricsSink",
    "NullEventPublisher",
    "NullMetricsSink",
    "Plan",
    "PlanStep",
    "RetryPolicy",
    "RetryableAgentError",
    "SelfEvaluation",
    "TaskContext",
    "TerminalAgentError",
]
