"""Exception hierarchy for AEP model providers, mirroring the retryable/terminal split used
platform-wide (docs/architecture/09-engineering-standards.md §6)."""

from __future__ import annotations


class ProviderError(Exception):
    """Base class for all provider errors."""


class ProviderRetryableError(ProviderError):
    """A transient failure (timeout, rate limit, transient 5xx) — eligible for automatic retry
    by ModelProvider's final generate()/stream()/embed() wrappers."""


class ProviderTerminalError(ProviderError):
    """A deterministic failure (bad request, invalid model, malformed tool schema) that
    retrying would not resolve."""


class ProviderRateLimitError(ProviderRetryableError):
    """Raised on a 429-equivalent response. Carries `retry_after_seconds` when the provider
    supplies one, which the retry wrapper honors over its own backoff schedule."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderAuthenticationError(ProviderTerminalError):
    """Raised on an invalid/expired API key — never retried, since retrying won't fix it."""


class ProviderContentFilterError(ProviderTerminalError):
    """Raised when the provider refuses to generate due to its own content policy."""


class ProviderModelNotFoundError(ProviderTerminalError):
    """Raised when `model` isn't recognized by this provider."""
