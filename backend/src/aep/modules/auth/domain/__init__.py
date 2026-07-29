"""Authentication Service domain layer — entities, value objects, and domain exceptions.
Zero framework imports (docs/architecture/02-repo-design.md §2)."""

from .errors import (
    AuthDomainError,
    InvalidRefreshTokenError,
    OAuthExchangeError,
    RoleAlreadyGrantedError,
    RoleNotFoundError,
    RoleNotGrantedError,
    UnsupportedOAuthProviderError,
    UserNotFoundError,
)
from .models import AuditEvent, RefreshToken, Role, User, UserRole, UserStatus

__all__ = [
    "AuditEvent",
    "AuthDomainError",
    "InvalidRefreshTokenError",
    "OAuthExchangeError",
    "RefreshToken",
    "Role",
    "RoleAlreadyGrantedError",
    "RoleNotFoundError",
    "RoleNotGrantedError",
    "UnsupportedOAuthProviderError",
    "User",
    "UserNotFoundError",
    "UserRole",
    "UserStatus",
]
