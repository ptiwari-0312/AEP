"""Evaluation Framework (host side) — runs the pluggable quality gate against agent output
before it's eligible for human approval. See `docs/architecture/07-evaluation-framework.md` and
`docs/architecture/04-api-design.md` §7.

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `EvaluationService` (for another module — e.g. a future
real Evaluation Framework-driven promotion in `orchestrator`, replacing its current self-
evaluation stand-in — to call into).
"""

from .api import router
from .services import EvaluationService

__all__ = ["EvaluationService", "router"]
