"""Context Builder — turns a Task ID into a ranked, deduplicated, token-budgeted Context Package
(docs/architecture/06-context-builder.md; docs/architecture/04-api-design.md §4).

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `ContextBuilderService` (for another module, e.g. a
future Agent Orchestrator, to call into — the same way this module calls into `task_memory`'s
`TaskService` and `projects`' `FeatureService`/`ProjectService`).
"""

from .api import router
from .services import ContextBuilderService

__all__ = ["ContextBuilderService", "router"]
