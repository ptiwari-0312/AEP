"""End-to-end test of the Authentication Service through the real HTTP API
(docs/architecture/02-repo-design.md §2: `tests/integration` is "cross-module, real DB").

The OAuth provider is swapped for a fake via FastAPI's `dependency_overrides` — no real GitHub
credentials or network access needed to exercise the login flow end-to-end.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.main import create_app
from aep.modules.auth.api.dependencies import get_oauth_providers
from aep.modules.auth.repository.models import RoleModel
from aep.modules.auth.repository.role_repository import RoleRepository
from aep.modules.auth.services.oauth import OAuthIdentity


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEP_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


class _FakeOAuthProvider:
    provider_name = "github"

    def __init__(self, email: str = "a@example.com", subject: str = "42") -> None:
        self._email = email
        self._subject = subject

    async def exchange_code(self, code: str) -> OAuthIdentity:
        return OAuthIdentity(provider="github", subject=self._subject, email=self._email, display_name="A")


@pytest.fixture
def app():
    application = create_app()
    application.dependency_overrides[get_oauth_providers] = lambda: {"github": _FakeOAuthProvider()}
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


async def _make_admin(user_id: str) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        role = RoleModel(id=uuid4(), name="admin")
        session.add(role)
        await session.flush()
        await RoleRepository(session).grant(UUID(user_id), role.id, granted_by=None)
        await session.commit()


def test_login_returns_tokens_and_user(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"provider": "github", "code": "any-code"})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "a@example.com"
    assert body["expires_in"] > 0
    assert "access_token" in body
    assert "refresh_token" in body


def test_login_rejects_unconfigured_provider(client: TestClient) -> None:
    response = client.post("/api/v1/auth/login", json={"provider": "okta", "code": "any-code"})

    assert response.status_code == 422


def test_get_me_requires_bearer_token(client: TestClient) -> None:
    response = client.get("/api/v1/users/me")

    assert response.status_code == 401


def test_get_me_returns_current_user(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()

    response = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {login['access_token']}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "a@example.com"
    assert response.json()["roles"] == []


def test_list_users_requires_admin_role(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()

    response = client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {login['access_token']}"}
    )

    assert response.status_code == 403


async def test_admin_can_list_users_grant_and_revoke_roles(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()
    user_id = login["user"]["id"]
    await _make_admin(user_id)

    # Re-login so the access token's `roles` claim picks up the freshly granted admin role.
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    list_response = client.get("/api/v1/users", headers=headers)
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    roles_response = client.get("/api/v1/roles", headers=headers)
    assert roles_response.status_code == 200
    role_names = {r["name"] for r in roles_response.json()}
    assert "admin" in role_names
    engineer_role_id = next(
        r["id"] for r in roles_response.json() if r["name"] == "admin"
    )

    # Re-grant the same (already-held) role to exercise the 409 path, then revoke and re-grant
    # cleanly to exercise both the DELETE and the successful POST paths.
    grant_response = client.post(
        f"/api/v1/users/{user_id}/roles", json={"role_id": engineer_role_id}, headers=headers
    )
    assert grant_response.status_code == 409  # admin role already granted directly above

    revoke_response = client.delete(
        f"/api/v1/users/{user_id}/roles/{engineer_role_id}", headers=headers
    )
    assert revoke_response.status_code == 204

    grant_again_response = client.post(
        f"/api/v1/users/{user_id}/roles", json={"role_id": engineer_role_id}, headers=headers
    )
    assert grant_again_response.status_code == 201


def test_refresh_and_logout_flow(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()

    refresh_response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert refresh_response.status_code == 200
    new_tokens = refresh_response.json()

    reused_response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert reused_response.status_code == 401

    logout_response = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": new_tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert logout_response.status_code == 204

    refresh_after_logout_response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert refresh_after_logout_response.status_code == 401


async def test_admin_can_query_audit_events(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()
    user_id = login["user"]["id"]
    await _make_admin(user_id)
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    response = client.get("/api/v1/audit-events", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["event_type"] == "user.login"


def test_audit_events_requires_admin(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()

    response = client.get(
        "/api/v1/audit-events", headers={"Authorization": f"Bearer {login['access_token']}"}
    )

    assert response.status_code == 403
