"""End-to-end test of the Prompt Library through the real HTTP API
(docs/architecture/02-repo-design.md §2: `tests/integration` is "cross-module, real DB" — though
this module is fully self-contained, with no cross-module calls).

Authenticates via a fake OAuth provider (dependency-overridden) since these endpoints require a
real bearer token — see the identical note in tests/integration/test_projects_api.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.main import create_app
from aep.modules.auth.api.dependencies import get_oauth_providers
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

    async def exchange_code(self, code: str) -> OAuthIdentity:
        return OAuthIdentity(provider="github", subject="1", email="a@example.com", display_name="A")


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[get_oauth_providers] = lambda: {"github": _FakeOAuthProvider()}
    with TestClient(app) as test_client:
        login = test_client.post("/api/v1/auth/login", json={"provider": "github", "code": "c"}).json()
        test_client.headers.update({"Authorization": f"Bearer {login['access_token']}"})
        yield test_client


def test_create_template_requires_unique_name(client: TestClient) -> None:
    body = {"name": "coding-agent-system-prompt", "description": "System prompt for CodingAgent"}
    first = client.post("/api/v1/prompt-templates", json=body)
    assert first.status_code == 201

    second = client.post("/api/v1/prompt-templates", json=body)
    assert second.status_code == 409


def test_full_version_lifecycle(client: TestClient) -> None:
    template = client.post(
        "/api/v1/prompt-templates", json={"name": "coding-agent-system-prompt"}
    ).json()
    template_id = template["id"]

    get_response = client.get(f"/api/v1/prompt-templates/{template_id}")
    assert get_response.status_code == 200
    assert get_response.json()["active_version"] is None

    v1_response = client.post(
        f"/api/v1/prompt-templates/{template_id}/versions",
        json={"content": "You are a coding agent named {{ name }}.", "variables": [{"name": "name"}]},
    )
    assert v1_response.status_code == 201
    v1 = v1_response.json()
    assert v1["version_number"] == 1
    assert v1["is_active"] is False

    v2_response = client.post(
        f"/api/v1/prompt-templates/{template_id}/versions",
        json={"content": "v2 content", "activate": True},
    )
    assert v2_response.status_code == 201
    v2 = v2_response.json()
    assert v2["version_number"] == 2
    assert v2["is_active"] is True

    get_after_activate = client.get(f"/api/v1/prompt-templates/{template_id}")
    assert get_after_activate.json()["active_version"]["version_number"] == 2

    list_response = client.get(f"/api/v1/prompt-templates/{template_id}/versions")
    assert list_response.status_code == 200
    assert [v["version_number"] for v in list_response.json()] == [1, 2]

    activate_v1 = client.post(
        f"/api/v1/prompt-templates/{template_id}/versions/1/activate"
    )
    assert activate_v1.status_code == 200
    assert activate_v1.json()["is_active"] is True

    v2_refetched = client.get(f"/api/v1/prompt-templates/{template_id}/versions/2")
    assert v2_refetched.json()["is_active"] is False

    already_active = client.post(
        f"/api/v1/prompt-templates/{template_id}/versions/1/activate"
    )
    assert already_active.status_code == 409


def test_create_version_rejects_undeclared_variable(client: TestClient) -> None:
    template = client.post("/api/v1/prompt-templates", json={"name": "t"}).json()

    response = client.post(
        f"/api/v1/prompt-templates/{template['id']}/versions",
        json={"content": "Hello {{ name }}"},
    )

    assert response.status_code == 422


def test_get_version_404_for_unknown_version_number(client: TestClient) -> None:
    template = client.post("/api/v1/prompt-templates", json={"name": "t"}).json()

    response = client.get(f"/api/v1/prompt-templates/{template['id']}/versions/99")

    assert response.status_code == 404


def test_get_template_404_when_missing(client: TestClient) -> None:
    response = client.get("/api/v1/prompt-templates/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_list_templates_paginates(client: TestClient) -> None:
    for i in range(3):
        client.post("/api/v1/prompt-templates", json={"name": f"t-{i}"})

    response = client.get("/api/v1/prompt-templates", params={"page": 1, "page_size": 2})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
