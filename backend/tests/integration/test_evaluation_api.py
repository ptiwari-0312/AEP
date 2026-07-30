"""End-to-end test of the Evaluation Framework through the real HTTP API, including its call
across the module boundary into `orchestrator`'s `AgentRunService`
(docs/architecture/02-repo-design.md §2: `tests/integration` is "cross-module, real DB").

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
from aep.modules.context_builder.repository.source_document_repository import (
    SourceDocumentRepository,
)
from aep.modules.context_builder.services.indexing import SourceDocumentIndexer
from aep.modules.orchestrator.services.run_registry import get_run_registry


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("AEP_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_run_registry.cache_clear()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    get_run_registry.cache_clear()


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
async def succeeded_run(client: TestClient, tmp_path) -> dict[str, str]:
    project = client.post("/api/v1/projects", json={"name": "AEP", "slug": "aep"}).json()
    feature = client.post(
        f"/api/v1/projects/{project['id']}/features", json={"title": "Add login"}
    ).json()
    task = client.post(
        f"/api/v1/features/{feature['id']}/tasks",
        json={"title": "Implement login", "task_type": "code"},
    ).json()
    client.post(f"/api/v1/tasks/{task['id']}/status", json={"to_status": "ready"})

    (tmp_path / "auth.py").write_text("def login(user):\n    return authenticate(user)\n")
    session_factory = get_session_factory()
    async with session_factory() as session:
        indexer = SourceDocumentIndexer(SourceDocumentRepository(session))
        await indexer.index_directory(UUID(project["id"]), tmp_path)
        await session.commit()

    package = client.post(
        f"/api/v1/tasks/{task['id']}/context-packages", json={"max_tokens": 100_000}
    ).json()
    agent = client.post(
        "/api/v1/agents", json={"name": "CodingAgent", "agent_type": "coding", "version": "1.0.0"}
    ).json()
    client.post(f"/api/v1/tasks/{task['id']}/assign", json={"agent_id": agent["id"]})

    run_id = client.post(
        f"/api/v1/tasks/{task['id']}/runs",
        json={
            "provider": "claude",
            "model_name": "claude-x",
            "context_package_id": package["job_id"],
        },
    ).json()["agent_run_id"]

    with client.stream("GET", f"/api/v1/agent-runs/{run_id}/events") as response:
        for _line in response.iter_lines():
            pass  # drain to the terminal event so the run is guaranteed persisted (see
            # orchestrator's README on agent_run.persisted)

    return {"task_id": task["id"], "agent_run_id": run_id}


def test_trigger_evaluations_and_read_quality_gate(
    client: TestClient, succeeded_run: dict[str, str]
) -> None:
    trigger_response = client.post(
        f"/api/v1/agent-runs/{succeeded_run['agent_run_id']}/evaluations",
        json={"evaluator_types": ["performance", "llm_judge"]},
    )
    assert trigger_response.status_code == 202
    body = trigger_response.json()
    assert body["status"] == "completed"
    assert len(body["evaluation_ids"]) == 2

    list_response = client.get(f"/api/v1/agent-runs/{succeeded_run['agent_run_id']}/evaluations")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2

    evaluation_id = body["evaluation_ids"][0]
    get_response = client.get(f"/api/v1/evaluations/{evaluation_id}")
    assert get_response.status_code == 200

    results_response = client.get(f"/api/v1/evaluations/{evaluation_id}/results")
    assert results_response.status_code == 200
    assert len(results_response.json()) >= 1

    gate_response = client.get(f"/api/v1/tasks/{succeeded_run['task_id']}/quality-gate")
    assert gate_response.status_code == 200
    gate_body = gate_response.json()
    assert gate_body["overall"] == "passed"
    assert gate_body["agent_run_id"] == succeeded_run["agent_run_id"]
    assert len(gate_body["evaluations"]) == 2


def test_trigger_evaluations_rejects_unknown_evaluator_type(
    client: TestClient, succeeded_run: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/agent-runs/{succeeded_run['agent_run_id']}/evaluations",
        json={"evaluator_types": ["not_a_real_type"]},
    )
    assert response.status_code == 422


def test_trigger_evaluations_rejects_unregistered_evaluator_type(
    client: TestClient, succeeded_run: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/agent-runs/{succeeded_run['agent_run_id']}/evaluations",
        json={"evaluator_types": ["unit_test"]},
    )
    assert response.status_code == 422


def test_trigger_evaluations_404_when_run_missing(client: TestClient) -> None:
    response = client.post(
        "/api/v1/agent-runs/00000000-0000-0000-0000-000000000000/evaluations",
        json={"evaluator_types": ["performance"]},
    )
    assert response.status_code == 404


def test_quality_gate_pending_when_task_has_no_runs(client: TestClient) -> None:
    project = client.post("/api/v1/projects", json={"name": "Other", "slug": "other"}).json()
    feature = client.post(
        f"/api/v1/projects/{project['id']}/features", json={"title": "F"}
    ).json()
    task = client.post(
        f"/api/v1/features/{feature['id']}/tasks", json={"title": "T", "task_type": "code"}
    ).json()

    response = client.get(f"/api/v1/tasks/{task['id']}/quality-gate")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "pending"
    assert body["agent_run_id"] is None


def test_quality_gate_404_when_task_missing(client: TestClient) -> None:
    response = client.get("/api/v1/tasks/00000000-0000-0000-0000-000000000000/quality-gate")
    assert response.status_code == 404
