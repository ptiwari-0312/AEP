"""End-to-end test of the Project Service through the real HTTP API, backed by a real
(SQLite) database — proves `api/`, `services/`, and `repository/` work together, not just each
layer in isolation (docs/architecture/02-repo-design.md §2: `tests/integration` is "cross-module,
real DB").
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.main import create_app


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


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_check(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_full_project_and_feature_lifecycle(client: TestClient) -> None:
    create_response = client.post(
        "/api/v1/projects", json={"name": "AEP", "slug": "aep", "description": "the platform"}
    )
    assert create_response.status_code == 201
    project = create_response.json()
    assert project["slug"] == "aep"
    assert project["status"] == "active"
    assert project["owner_user_id"] == "00000000-0000-0000-0000-000000000001"

    get_response = client.get(f"/api/v1/projects/{project['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "AEP"

    list_response = client.get("/api/v1/projects")
    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] == 1
    assert listed["page"] == 1
    assert listed["page_size"] == 20

    duplicate_response = client.post("/api/v1/projects", json={"name": "Dup", "slug": "aep"})
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["type"] == "https://aep.dev/errors/ConflictError"

    update_response = client.patch(f"/api/v1/projects/{project['id']}", json={"name": "AEP Renamed"})
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "AEP Renamed"

    repo_response = client.put(
        f"/api/v1/projects/{project['id']}/repository",
        json={"name": "aep-repo", "url": "https://github.com/example/aep", "provider": "github"},
    )
    assert repo_response.status_code == 200
    assert repo_response.json()["git_repository_id"] is not None

    feature_response = client.post(
        f"/api/v1/projects/{project['id']}/features", json={"title": "Dashboard"}
    )
    assert feature_response.status_code == 201
    feature = feature_response.json()
    assert feature["status"] == "draft"
    assert feature["created_by"] == "00000000-0000-0000-0000-000000000001"

    features_list_response = client.get(f"/api/v1/projects/{project['id']}/features")
    assert features_list_response.status_code == 200
    assert len(features_list_response.json()) == 1

    transition_response = client.post(
        f"/api/v1/features/{feature['id']}/status", json={"to_status": "in_progress"}
    )
    assert transition_response.status_code == 200
    assert transition_response.json()["status"] == "in_progress"

    illegal_transition_response = client.post(
        f"/api/v1/features/{feature['id']}/status", json={"to_status": "done"}
    )
    assert illegal_transition_response.status_code == 409

    archive_response = client.post(f"/api/v1/projects/{project['id']}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["status"] == "archived"

    double_archive_response = client.post(f"/api/v1/projects/{project['id']}/archive")
    assert double_archive_response.status_code == 409

    not_found_response = client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000")
    assert not_found_response.status_code == 404
    assert not_found_response.json()["type"] == "https://aep.dev/errors/NotFoundError"


def test_create_project_rejects_invalid_slug(client: TestClient) -> None:
    response = client.post("/api/v1/projects", json={"name": "Bad Slug", "slug": "Not A Slug!"})
    assert response.status_code == 422
