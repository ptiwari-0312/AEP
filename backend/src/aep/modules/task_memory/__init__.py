"""Task Memory Service — owns the Task Graph (tasks, dependencies, state, history) derived
from a Feature (docs/architecture/01-vision-and-principles.md §4;
docs/architecture/04-api-design.md §3).

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `TaskService` (for another module to call into, the
same way this module calls into the Project Service's `FeatureService`).
"""

from .api import router
from .services import TaskService

__all__ = ["TaskService", "router"]
