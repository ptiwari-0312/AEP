"""Maps the official Anthropic SDK's exceptions onto AEP's retryable/terminal error hierarchy
(docs/architecture/01-vision-and-principles.md ADR-002; sdk/aep-provider-sdk's errors.py)."""

from __future__ import annotations

import anthropic
from aep_provider_sdk import (
    ProviderAuthenticationError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderRetryableError,
    ProviderTerminalError,
)


def map_anthropic_error(exc: Exception) -> Exception:
    # Order matters: RateLimitError/AuthenticationError/NotFoundError are all subclasses of
    # APIStatusError, so they must be checked before the generic APIStatusError fallback.
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderRateLimitError(str(exc), retry_after_seconds=_extract_retry_after(exc))
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderAuthenticationError(str(exc))
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderModelNotFoundError(str(exc))
    if isinstance(exc, anthropic.APIConnectionError | anthropic.InternalServerError):
        # APITimeoutError is a subclass of APIConnectionError, covered here too.
        return ProviderRetryableError(str(exc))
    if isinstance(exc, anthropic.APIStatusError):
        return ProviderTerminalError(str(exc))
    return ProviderTerminalError(str(exc))


def _extract_retry_after(exc: anthropic.RateLimitError) -> float | None:
    value = exc.response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
