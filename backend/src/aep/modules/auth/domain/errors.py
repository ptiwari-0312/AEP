"""Domain-level errors for the Authentication Service — pure Python, no framework imports."""

from __future__ import annotations

from uuid import UUID


class AuthDomainError(Exception):
    """Base class for every Authentication Service domain error."""


class UserNotFoundError(AuthDomainError):
    def __init__(self, user_id: UUID) -> None:
        super().__init__(f"user {user_id} not found")
        self.user_id = user_id


class RoleNotFoundError(AuthDomainError):
    def __init__(self, role_id: UUID) -> None:
        super().__init__(f"role {role_id} not found")
        self.role_id = role_id


class RoleAlreadyGrantedError(AuthDomainError):
    def __init__(self, user_id: UUID, role_id: UUID) -> None:
        super().__init__(f"user {user_id} already has role {role_id}")
        self.user_id = user_id
        self.role_id = role_id


class RoleNotGrantedError(AuthDomainError):
    def __init__(self, user_id: UUID, role_id: UUID) -> None:
        super().__init__(f"user {user_id} does not have role {role_id}")
        self.user_id = user_id
        self.role_id = role_id


class UnsupportedOAuthProviderError(AuthDomainError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"unsupported OAuth provider {provider!r}")
        self.provider = provider


class OAuthExchangeError(AuthDomainError):
    """The OAuth provider rejected the code, or the exchange otherwise failed."""


class InvalidRefreshTokenError(AuthDomainError):
    def __init__(self) -> None:
        super().__init__("refresh token is invalid, expired, or revoked")
