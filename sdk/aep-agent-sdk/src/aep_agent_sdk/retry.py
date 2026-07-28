"""Retry policy (docs/architecture/05-agent-sdk.md §6)."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import RetryableAgentError


@dataclass(frozen=True)
class RetryPolicy:
    """Retryable vs. terminal is a first-class distinction, not "retry everything until
    max_attempts": only error types in `retryable_error_types` are retried at all, and
    `AgentCancelledError` is never retried regardless of this configuration (enforced by
    BaseAgent.run(), not here)."""

    max_attempts: int = 3
    backoff_base_seconds: float = 2.0
    backoff_multiplier: float = 2.0
    retryable_error_types: tuple[type[Exception], ...] = (RetryableAgentError,)

    def backoff_seconds(self, attempt_number: int) -> float:
        return self.backoff_base_seconds * (self.backoff_multiplier ** (attempt_number - 1))

    def is_retryable(self, error: BaseException) -> bool:
        return isinstance(error, self.retryable_error_types)
