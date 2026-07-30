"""Prompt Library — versioned, testable prompt templates consumed by agents; decouples prompt
iteration from agent code changes. See `docs/architecture/04-api-design.md` §6 and
`docs/architecture/09-engineering-standards.md` §9.

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `PromptLibraryService` (for another module — e.g. a
future real agent implementation that loads its system prompt by template name instead of
hardcoding it, per the engineering standards doc's own requirement — to call into).
"""

from .api import router
from .services import PromptLibraryService

__all__ = ["PromptLibraryService", "router"]
