"""Authentication Service persistence layer — SQLAlchemy models and repository classes.
Depends on `aep.core.db` and `aep.core.pagination` only (docs/architecture/02-repo-design.md §2)."""

from .audit_event_repository import AuditEventRepository
from .models import (
    AuditEventModel,
    RefreshTokenModel,
    RoleModel,
    UserModel,
    UserRoleModel,
)
from .refresh_token_repository import RefreshTokenRepository
from .role_repository import RoleRepository
from .user_repository import UserRepository

__all__ = [
    "AuditEventModel",
    "AuditEventRepository",
    "RefreshTokenModel",
    "RefreshTokenRepository",
    "RoleModel",
    "RoleRepository",
    "UserModel",
    "UserRepository",
    "UserRoleModel",
]
