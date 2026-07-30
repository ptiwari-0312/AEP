"""Dashboard API — composes the other modules into the read/write surface the React frontend
uses; owns no domain logic of its own. See `docs/architecture/04-api-design.md` §11.

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `DashboardService`.
"""

from .api import router
from .services import DashboardService

__all__ = ["DashboardService", "router"]
