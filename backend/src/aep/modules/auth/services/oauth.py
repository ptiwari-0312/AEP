"""OAuth code-exchange providers (docs/architecture/04-api-design.md §1:
`POST /auth/login` accepts `provider: "github"|"google"|"okta"`).

Only GitHub is actually implemented. Google/Okta are real gaps, not oversights — faking them
with a stub that returns canned data would be worse than not having them: `AuthService` raises
`UnsupportedOAuthProviderError` for any provider name without a registered `OAuthProvider`,
which is the honest state until someone registers a real one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from ..domain.errors import OAuthExchangeError


@dataclass
class OAuthIdentity:
    provider: str
    subject: str
    email: str
    display_name: str


@runtime_checkable
class OAuthProvider(Protocol):
    provider_name: str

    async def exchange_code(self, code: str) -> OAuthIdentity: ...


class GitHubOAuthProvider:
    """Exchanges a GitHub OAuth `code` for the user's identity via GitHub's real token and user
    endpoints (https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps).
    """

    provider_name = "github"

    def __init__(
        self, *, client_id: str, client_secret: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._client = client or httpx.AsyncClient()

    async def exchange_code(self, code: str) -> OAuthIdentity:
        token_response = await self._client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        if token_response.status_code != 200:
            raise OAuthExchangeError(
                f"GitHub token exchange failed with status {token_response.status_code}"
            )
        token_data = token_response.json()
        if "error" in token_data:
            raise OAuthExchangeError(
                f"GitHub rejected the code: {token_data.get('error_description', token_data['error'])}"
            )
        access_token = token_data["access_token"]
        auth_header = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }

        user_response = await self._client.get("https://api.github.com/user", headers=auth_header)
        if user_response.status_code != 200:
            raise OAuthExchangeError(
                f"GitHub user lookup failed with status {user_response.status_code}"
            )
        user_data = user_response.json()

        email = user_data.get("email")
        if not email:
            # GitHub's primary email can be private, in which case /user omits it entirely —
            # fall back to the emails endpoint, which requires the same access token.
            emails_response = await self._client.get(
                "https://api.github.com/user/emails", headers=auth_header
            )
            if emails_response.status_code == 200:
                emails = emails_response.json()
                primary = next((e for e in emails if e.get("primary")), None)
                email = (primary or {}).get("email") or (emails[0]["email"] if emails else None)
        if not email:
            raise OAuthExchangeError("GitHub account has no accessible email address")

        return OAuthIdentity(
            provider=self.provider_name,
            subject=str(user_data["id"]),
            email=email,
            display_name=user_data.get("name") or user_data["login"],
        )
