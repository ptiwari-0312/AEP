"""Cooperative cancellation (docs/architecture/05-agent-sdk.md §7)."""

from __future__ import annotations

import asyncio

from .errors import AgentCancelledError


class CancellationToken:
    """Passed into execute(). Cancellation here is cooperative, not preemptive: an agent
    mid-write must be given the chance to reach a safe checkpoint, so this token is polled,
    never used to forcibly kill the running coroutine. Agents should call
    `raise_if_cancelled()` (or check `is_cancelled`) between tool calls / plan steps."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        """Suspend until cancelled — useful to race against other awaitables via
        `asyncio.wait()` from inside execute()."""
        await self._event.wait()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise AgentCancelledError("cancellation requested")
