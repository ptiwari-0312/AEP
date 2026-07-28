"""Exception hierarchy for AEP agents (docs/architecture/05-agent-sdk.md §6)."""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all agent errors."""


class RetryableAgentError(AgentError):
    """A transient failure (provider timeout, rate limit, sandbox unavailable) — eligible for
    automatic retry under a RetryPolicy."""


class TerminalAgentError(AgentError):
    """A deterministic failure (bad config, invalid context, a hard self-evaluation failure)
    that retrying would not resolve."""


class AgentTimeoutError(RetryableAgentError):
    """Raised when a heartbeat window is missed; retryable like any other transient failure
    (docs/architecture/05-agent-sdk.md §8)."""


class AgentCancelledError(AgentError):
    """Raised when a CancellationToken is observed as cancelled; never retried automatically,
    regardless of RetryPolicy configuration."""
