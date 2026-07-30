"""Metrics Service — aggregates cost, latency, token usage, and quality trends across agents,
providers, and teams. See `docs/architecture/04-api-design.md` §9.

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `MetricsService` — in particular `record_metric()`,
the internal write path other modules (e.g. `orchestrator` on run completion, `evaluation` on
evaluation completion) are meant to call into, the same pattern as `auth.AuditService`.
"""

from .api import router
from .services import MetricsService

__all__ = ["MetricsService", "router"]
