"""Project Service — owns Projects and Features
(docs/architecture/01-vision-and-principles.md §4; docs/architecture/04-api-design.md §2).

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `services/` classes (for another module to call into,
per the "cross-module calls go through the other module's services/ public interface" rule —
never that module's `domain/`/`repository/` directly).
"""

from .api import router
from .services import FeatureService, ProjectService

__all__ = ["FeatureService", "ProjectService", "router"]
