"""Authentication Service — OAuth/JWT identity, RBAC, and the audit-event source of truth for
"who did what" (docs/architecture/01-vision-and-principles.md §4;
docs/architecture/04-api-design.md §1, §10).

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `services/` classes (for another module to call into).
"""

from .api import router
from .services import AuditService, AuthService, UserService

__all__ = ["AuditService", "AuthService", "UserService", "router"]
