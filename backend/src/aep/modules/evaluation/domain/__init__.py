"""Evaluation Framework domain layer — entities, value objects, and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import (
    AgentRunNotFoundError,
    AgentRunNotSucceededError,
    EvaluationDomainError,
    EvaluationNotFoundError,
    EvaluatorTypeNotRegisteredError,
    TaskNotFoundError,
)
from .models import (
    Evaluation,
    EvaluationResult,
    EvaluationStatus,
    EvaluatorType,
    QualityGateEvaluationSummary,
    QualityGateResult,
)

__all__ = [
    "AgentRunNotFoundError",
    "AgentRunNotSucceededError",
    "Evaluation",
    "EvaluationDomainError",
    "EvaluationNotFoundError",
    "EvaluationResult",
    "EvaluationStatus",
    "EvaluatorType",
    "EvaluatorTypeNotRegisteredError",
    "QualityGateEvaluationSummary",
    "QualityGateResult",
    "TaskNotFoundError",
]
