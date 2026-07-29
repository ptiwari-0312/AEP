"""JWT issuance/verification and RBAC dependencies (docs/architecture/02-repo-design.md §2).

Roles are carried as a claim inside the access token, resolved once at issuance time by the
Authentication Service (docs/architecture/04-api-design.md §0.2: "The JWT is issued by the
Authentication Service and carries the caller's user_id and resolved roles") — so every other
module's authorization check is a pure JWT decode, never a database round trip. The trade-off,
deliberate: a role grant/revoke doesn't take effect until the user's token is next refreshed, not
instantly. This module only verifies/decodes; deciding *when* to issue a token and what claims it
carries beyond the generic (user_id, roles) is the `auth` module's `services/` concern — this
stays free of persistence and OAuth-flow business logic, matching `core/`'s "zero business
logic" rule (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from .config import Settings, get_settings
from .errors import ForbiddenError, UnauthorizedError

_bearer_scheme = HTTPBearer(auto_error=False)
_ACCESS_TOKEN_TYPE = "access"


class AuthenticatedUser:
    """The identity and resolved roles decoded from a verified access token."""

    def __init__(self, user_id: UUID, roles: list[str]) -> None:
        self.user_id = user_id
        self.roles = roles

    def has_role(self, role: str) -> bool:
        # "Roles are additive — admin satisfies any lower requirement" (API design §0.2).
        return role in self.roles or "admin" in self.roles


def create_access_token(
    *, user_id: UUID, roles: list[str], settings: Settings | None = None
) -> tuple[str, int]:
    """Returns `(token, expires_in_seconds)`."""
    settings = settings or get_settings()
    expires_in = settings.jwt_access_token_expire_minutes * 60
    now = datetime.now(UTC)
    claims = {
        "sub": str(user_id),
        "roles": roles,
        "type": _ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str, *, settings: Settings | None = None) -> AuthenticatedUser:
    settings = settings or get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError as exc:
        raise UnauthorizedError("access token has expired") from exc
    except JWTError as exc:
        raise UnauthorizedError("access token is invalid") from exc
    if claims.get("type") != _ACCESS_TOKEN_TYPE:
        raise UnauthorizedError("not an access token")
    return AuthenticatedUser(user_id=UUID(claims["sub"]), roles=list(claims.get("roles", [])))


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthenticatedUser:
    if credentials is None:
        raise UnauthorizedError("missing bearer token")
    return decode_access_token(credentials.credentials)


async def get_current_user_id(user: AuthenticatedUser = Depends(get_current_user)) -> UUID:
    """The real replacement for the placeholder `get_current_user_id()` that
    `modules/projects/api/dependencies.py` and `modules/task_memory/api/dependencies.py`
    originally defined locally, pending this module's existence."""
    return user.user_id


def require_role(role: str):
    """Dependency factory: `Depends(require_role("admin"))`."""

    async def _dependency(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not user.has_role(role):
            raise ForbiddenError(f"this action requires the {role!r} role")
        return user

    return _dependency
