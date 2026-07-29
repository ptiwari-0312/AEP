from __future__ import annotations

import httpx
import pytest

from aep.modules.auth.domain.errors import OAuthExchangeError
from aep.modules.auth.services.oauth import GitHubOAuthProvider


def _client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_exchange_code_returns_identity_when_email_is_public() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "gho_abc123", "token_type": "bearer"})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            return httpx.Response(
                200, json={"id": 42, "login": "octocat", "name": "The Octocat", "email": "octo@example.com"}
            )
        raise AssertionError(f"unexpected request: {request.url}")

    provider = GitHubOAuthProvider(
        client_id="cid", client_secret="secret", client=_client_with(handler)
    )

    identity = await provider.exchange_code("real-code")

    assert identity.provider == "github"
    assert identity.subject == "42"
    assert identity.email == "octo@example.com"
    assert identity.display_name == "The Octocat"


async def test_exchange_code_falls_back_to_emails_endpoint_when_email_is_private() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "gho_abc123"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 42, "login": "octocat", "name": None, "email": None})
        if request.url.path == "/user/emails":
            return httpx.Response(
                200,
                json=[
                    {"email": "secondary@example.com", "primary": False, "verified": True},
                    {"email": "primary@example.com", "primary": True, "verified": True},
                ],
            )
        raise AssertionError(f"unexpected request: {request.url}")

    provider = GitHubOAuthProvider(
        client_id="cid", client_secret="secret", client=_client_with(handler)
    )

    identity = await provider.exchange_code("real-code")

    assert identity.email == "primary@example.com"
    assert identity.display_name == "octocat"  # falls back to login when name is null


async def test_exchange_code_raises_when_github_rejects_the_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": "bad_verification_code", "error_description": "The code passed is incorrect."}
        )

    provider = GitHubOAuthProvider(
        client_id="cid", client_secret="secret", client=_client_with(handler)
    )

    with pytest.raises(OAuthExchangeError, match="incorrect"):
        await provider.exchange_code("bad-code")


async def test_exchange_code_raises_on_non_200_from_token_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    provider = GitHubOAuthProvider(
        client_id="cid", client_secret="secret", client=_client_with(handler)
    )

    with pytest.raises(OAuthExchangeError, match="500"):
        await provider.exchange_code("code")


async def test_exchange_code_raises_when_no_email_is_ever_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/login/oauth/access_token":
            return httpx.Response(200, json={"access_token": "gho_abc123"})
        if request.url.path == "/user":
            return httpx.Response(200, json={"id": 42, "login": "octocat", "email": None})
        if request.url.path == "/user/emails":
            return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request: {request.url}")

    provider = GitHubOAuthProvider(
        client_id="cid", client_secret="secret", client=_client_with(handler)
    )

    with pytest.raises(OAuthExchangeError, match="no accessible email"):
        await provider.exchange_code("code")
