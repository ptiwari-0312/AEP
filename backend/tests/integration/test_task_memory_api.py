"""End-to-end test of the Task Memory Service through the real HTTP API, including its call
into the Project Service module's FeatureService across the module boundary
(docs/architecture/02-repo-design.md §2: `tests/integration` is "cross-module, real DB").

Authenticates via a fake OAuth provider (dependency-overridden) since these endpoints now
require a real bearer token — see the identical note in tests/integration/test_projects_api.py.
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


@pytest.fixture
def feature_id(client: TestClient) -> str:
    project = client.post("/api/v1/projects", json={"name": "AEP", "slug": "aep"}).json()
    feature = client.post(
        f"/api/v1/projects/{project['id']}/features", json={"title": "Dashboard"}
    ).json()
    return feature["id"]


def test_create_task_requires_a_real_feature(client: TestClient) -> None:
    response = client.post(
        "/api/v1/features/00000000-0000-0000-0000-000000000000/tasks",
        json={"title": "X", "task_type": "code"},
    )
    assert response.status_code == 404
    assert response.json()["type"] == "https://aep.dev/errors/NotFoundError"


def test_full_task_lifecycle_with_dependency_gate(client: TestClient, feature_id: str) -> None:
    blocker = client.post(
        f"/api/v1/features/{feature_id}/tasks", json={"title": "Design schema", "task_type": "architect"}
    ).json()
    dependent = client.post(
        f"/api/v1/features/{feature_id}/tasks", json={"title": "Implement endpoint", "task_type": "code"}
    ).json()
    assert blocker["status"] == "pending"
    assert dependent["depends_on"] == []

    dep_response = client.post(
        f"/api/v1/tasks/{dependent['id']}/dependencies", json={"depends_on_task_id": blocker["id"]}
    )
    assert dep_response.status_code == 201
    dependency = dep_response.json()

    get_response = client.get(f"/api/v1/tasks/{dependent['id']}")
    assert get_response.json()["depends_on"] == [blocker["id"]]

    # Self-dependency and cycles are rejected.
    self_dep_response = client.post(
        f"/api/v1/tasks/{dependent['id']}/dependencies", json={"depends_on_task_id": dependent["id"]}
    )
    assert self_dep_response.status_code == 409

    cycle_response = client.post(
        f"/api/v1/tasks/{blocker['id']}/dependencies", json={"depends_on_task_id": dependent["id"]}
    )
    assert cycle_response.status_code == 409

    # Becoming READY doesn't require the blocker to be merged yet...
    ready_response = client.post(f"/api/v1/tasks/{dependent['id']}/status", json={"to_status": "ready"})
    assert ready_response.status_code == 200
    # ...but RUNNING does.
    blocked_response = client.post(f"/api/v1/tasks/{dependent['id']}/status", json={"to_status": "running"})
    assert blocked_response.status_code == 409

    # Walk the blocker to merged.
    for status in ("ready", "running", "evaluating", "awaiting_approval", "approved", "merged"):
        step = client.post(f"/api/v1/tasks/{blocker['id']}/status", json={"to_status": status})
        assert step.status_code == 200, step.json()

    now_runnable = client.post(f"/api/v1/tasks/{dependent['id']}/status", json={"to_status": "running"})
    assert now_runnable.status_code == 200
    assert now_runnable.json()["status"] == "running"

    illegal_response = client.post(f"/api/v1/tasks/{dependent['id']}/status", json={"to_status": "merged"})
    assert illegal_response.status_code == 409

    history_response = client.get(f"/api/v1/tasks/{dependent['id']}/execution-history")
    assert history_response.status_code == 200
    history = history_response.json()
    assert history["items"][0]["to_status"] == "running"
    assert history["items"][-1]["to_status"] == "ready"
    assert history["has_more"] is False

    update_response = client.patch(f"/api/v1/tasks/{dependent['id']}", json={"priority": 3})
    assert update_response.status_code == 200
    assert update_response.json()["priority"] == 3

    remove_response = client.delete(f"/api/v1/tasks/{dependent['id']}/dependencies/{dependency['id']}")
    assert remove_response.status_code == 204

    reloaded = client.get(f"/api/v1/tasks/{dependent['id']}")
    assert reloaded.json()["depends_on"] == []


def test_list_tasks_paginates_with_cursor(client: TestClient, feature_id: str) -> None:
    for i in range(3):
        client.post(f"/api/v1/features/{feature_id}/tasks", json={"title": f"Task {i}", "task_type": "code"})

    first_page = client.get(f"/api/v1/features/{feature_id}/tasks", params={"limit": 2}).json()
    assert len(first_page["items"]) == 2
    assert first_page["has_more"] is True
    assert first_page["next_cursor"] is not None

    second_page = client.get(
        f"/api/v1/features/{feature_id}/tasks", params={"limit": 2, "cursor": first_page["next_cursor"]}
    ).json()
    assert len(second_page["items"]) == 1
    assert second_page["has_more"] is False


def test_task_not_found_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
