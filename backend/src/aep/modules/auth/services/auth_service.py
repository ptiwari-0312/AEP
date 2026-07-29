"""Login/refresh/logout orchestration (docs/architecture/04-api-design.md §1).

Refresh tokens are rotated on every use — the token presented to `refresh()` is revoked and a
new one issued, even though the API doc doesn't spell this out explicitly. This is standard
practice (not this doc's invention): if a refresh token is ever stolen, rotation means it can be
used at most once before either the legitimate user or the attacker's use invalidates it,
surfacing the theft rather than granting silent indefinite access.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from aep.core.db import ensure_utc, utcnow
from aep.core.security import create_access_token

from ..domain.errors import InvalidRefreshTokenError, UnsupportedOAuthProviderError
from ..domain.models import RefreshToken, User
from ..repository.refresh_token_repository import RefreshTokenRepository
from ..repository.role_repository import RoleRepository
from ..repository.user_repository import UserRepository
from .audit_service import AuditService
from .oauth import OAuthProvider


class LoginResult:
    def __init__(self, access_token: str, refresh_token: str, expires_in: int, user: User) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in
        self.user = user


class RefreshResult:
    def __init__(self, access_token: str, refresh_token: str, expires_in: int) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in


class AuthService:
    def __init__(
        self,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        refresh_token_repository: RefreshTokenRepository,
        oauth_providers: dict[str, OAuthProvider],
        audit_service: AuditService,
        *,
        refresh_token_expire_days: int = 30,
    ) -> None:
        self._users = user_repository
        self._roles = role_repository
        self._refresh_tokens = refresh_token_repository
        self._oauth_providers = oauth_providers
        self._audit = audit_service
        self._refresh_token_expire_days = refresh_token_expire_days

    async def login(self, *, provider: str, code: str) -> LoginResult:
        oauth_provider = self._oauth_providers.get(provider)
        if oauth_provider is None:
            raise UnsupportedOAuthProviderError(provider)
        identity = await oauth_provider.exchange_code(code)

        user = await self._users.get_by_provider_subject(identity.provider, identity.subject)
        if user is None:
            user = await self._users.add(
                User(
                    id=uuid4(),
                    email=identity.email,
                    display_name=identity.display_name,
                    auth_provider=identity.provider,
                    auth_subject=identity.subject,
                )
            )

        role_names = await self._roles.list_role_names_for_user(user.id)
        access_token, expires_in = create_access_token(user_id=user.id, roles=role_names)
        refresh_token = await self._issue_refresh_token(user.id)
        user.roles = role_names

        # The one write-path this pass wires end-to-end (see AuditService's docstring): proves
        # record_event() works against a real login, without retrofitting every other module's
        # mutating endpoints to call it too.
        await self._audit.record_event(
            event_type="user.login",
            entity_type="user",
            entity_id=user.id,
            actor_user_id=user.id,
            payload={"provider": provider},
        )
        return LoginResult(access_token, refresh_token, expires_in, user)

    async def refresh(self, *, refresh_token: str) -> RefreshResult:
        stored = await self._refresh_tokens.get_by_hash(_hash_token(refresh_token))
        if stored is None or not _is_valid(stored):
            raise InvalidRefreshTokenError()

        await self._refresh_tokens.revoke(stored.id)
        role_names = await self._roles.list_role_names_for_user(stored.user_id)
        access_token, expires_in = create_access_token(user_id=stored.user_id, roles=role_names)
        new_refresh_token = await self._issue_refresh_token(stored.user_id)
        return RefreshResult(access_token, new_refresh_token, expires_in)

    async def logout(self, *, refresh_token: str) -> None:
        stored = await self._refresh_tokens.get_by_hash(_hash_token(refresh_token))
        if stored is not None and _is_valid(stored):
            await self._refresh_tokens.revoke(stored.id)

    async def _issue_refresh_token(self, user_id: UUID) -> str:
        raw_token = secrets.token_urlsafe(32)
        await self._refresh_tokens.add(
            RefreshToken(
                id=uuid4(),
                user_id=user_id,
                token_hash=_hash_token(raw_token),
                expires_at=utcnow() + timedelta(days=self._refresh_token_expire_days),
            )
        )
        return raw_token


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _is_valid(refresh_token: RefreshToken) -> bool:
    return refresh_token.revoked_at is None and ensure_utc(refresh_token.expires_at) > utcnow()
