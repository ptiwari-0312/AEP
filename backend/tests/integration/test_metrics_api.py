"""End-to-end test of the Metrics Service through the real HTTP API, including its call across
the module boundary into `projects`' `ProjectService` for the project-scoped rollup endpoint
(docs/architecture/02-repo-design.md §2: `tests/integration` is "cross-module, real DB").

There's no HTTP endpoint to *write* a metric (docs/architecture/04-api-design.md §9: "writes
happen internally") — this test seeds `metrics` rows by calling `MetricsService.record_metric()`
directly against the same test database the API's `TestClient` is using, then exercises the
read-only endpoints entirely through real HTTP requests.

Authenticates via a fake OAuth provider (dependency-overridden) since these endpoints require a
real bearer token — see the identical note in tests/integration/test_projects_api.py.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.main import create_app
from aep.modules.auth.api.dependencies import get_oauth_providers
from aep.modules.auth.services.oauth import OAuthIdentity
from aep.modules.metrics.repository.metric_repository import MetricRepository
from aep.modules.metrics.services.metrics_service import MetricsService
from aep.modules.projects.repository.project_repository import ProjectRepository
from aep.modules.projects.services import ProjectService


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
async def project(client: TestClient) -> dict[str, str]:
    return client.post("/api/v1/projects", json={"name": "AEP", "slug": "aep"}).json()


async def _record(project_id: str, metric_name: str, value: float) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = MetricsService(MetricRepository(session), ProjectService(ProjectRepository(session)))
        await service.record_metric(
            metric_name=metric_name, entity_type="project", entity_id=UUID(project_id), value=value
        )
        await session.commit()


async def test_list_metrics_requires_metric_name(client: TestClient, project) -> None:
    missing_param_response = client.get("/api/v1/metrics")
    assert missing_param_response.status_code == 422

    await _record(project["id"], "cost_usd", 1.5)
    ok_response = client.get("/api/v1/metrics", params={"metric_name": "cost_usd"})
    assert ok_response.status_code == 200
    assert len(ok_response.json()["items"]) == 1


async def test_metrics_summary_group_by_project(client: TestClient, project) -> None:
    await _record(project["id"], "cost_usd", 1.0)
    await _record(project["id"], "cost_usd", 3.0)

    response = client.get(
        "/api/v1/metrics/summary",
        params={"metric_name": "cost_usd", "group_by": "project", "agg": "sum"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["buckets"] == [{"key": project["id"], "value": 4.0}]


def test_metrics_summary_rejects_provider_group_by(client: TestClient) -> None:
    response = client.get(
        "/api/v1/metrics/summary",
        params={"metric_name": "cost_usd", "group_by": "provider"},
    )
    assert response.status_code == 422


async def test_project_metrics_summary_rollup(client: TestClient, project) -> None:
    await _record(project["id"], "cost_usd", 2.0)
    await _record(project["id"], "cost_usd", 4.0)

    response = client.get(f"/api/v1/projects/{project['id']}/metrics/summary")

    assert response.status_code == 200
    body = response.json()
    entry = next(e for e in body["metrics"] if e["metric_name"] == "cost_usd")
    assert entry["sum"] == 6.0
    assert entry["count"] == 2


def test_project_metrics_summary_404_when_project_missing(client: TestClient) -> None:
    response = client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/metrics/summary"
    )
    assert response.status_code == 404
