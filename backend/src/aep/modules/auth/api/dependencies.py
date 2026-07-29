"""FastAPI dependency providers for the Authentication Service."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.config import Settings, get_settings
from aep.core.db import get_db_session

from ..repository.audit_event_repository import AuditEventRepository
from ..repository.refresh_token_repository import RefreshTokenRepository
from ..repository.role_repository import RoleRepository
from ..repository.user_repository import UserRepository
from ..services.audit_service import AuditService
from ..services.auth_service import AuthService
from ..services.oauth import GitHubOAuthProvider, OAuthProvider
from ..services.user_service import UserService


def get_oauth_providers(settings: Settings = Depends(get_settings)) -> dict[str, OAuthProvider]:
    """Only providers with real credentials configured are registered — `AuthService` raises
    `UnsupportedOAuthProviderError` (mapped to 422, "provider must be one of the configured
    providers" per docs/architecture/04-api-design.md §1) for anything else, rather than this
    silently pretending google/okta work."""
    providers: dict[str, OAuthProvider] = {}
    if settings.github_oauth_client_id and settings.github_oauth_client_secret:
        providers["github"] = GitHubOAuthProvider(
            client_id=settings.github_oauth_client_id,
            client_secret=settings.github_oauth_client_secret,
        )
    return providers


def get_audit_service(session: AsyncSession = Depends(get_db_session)) -> AuditService:
    return AuditService(AuditEventRepository(session))


def get_auth_service(
    session: AsyncSession = Depends(get_db_session),
    oauth_providers: dict[str, OAuthProvider] = Depends(get_oauth_providers),
    audit_service: AuditService = Depends(get_audit_service),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(
        UserRepository(session),
        RoleRepository(session),
        RefreshTokenRepository(session),
        oauth_providers,
        audit_service,
        refresh_token_expire_days=settings.jwt_refresh_token_expire_days,
    )


def get_user_service(session: AsyncSession = Depends(get_db_session)) -> UserService:
    return UserService(UserRepository(session), RoleRepository(session))
