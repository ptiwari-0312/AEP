"""Retry policy for transient provider errors (rate limits, timeouts)."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ProviderRetryableError


@dataclass(frozen=True)
class ProviderRetryPolicy:
    max_attempts: int = 3
    backoff_base_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    retryable_error_types: tuple[type[Exception], ...] = (ProviderRetryableError,)

    def backoff_seconds(
        self, attempt_number: int, *, retry_after_seconds: float | None = None
    ) -> float:
        """Honors a provider-supplied `retry_after_seconds` (e.g. from a 429 response) over
        our own exponential schedule — the provider knows its own rate limit window better
        than a generic backoff guess does."""
        if retry_after_seconds is not None:
            return retry_after_seconds
        return self.backoff_base_seconds * (self.backoff_multiplier ** (attempt_number - 1))

    def is_retryable(self, error: BaseException) -> bool:
        return isinstance(error, self.retryable_error_types)
