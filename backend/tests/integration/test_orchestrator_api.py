"""End-to-end test of the Agent Orchestrator through the real HTTP API, including its calls
across the module boundary into `task_memory`'s `TaskService`, `context_builder`'s
`ContextBuilderService`, and `auth`'s `AuditService` (docs/architecture/02-repo-design.md §2:
`tests/integration` is "cross-module, real DB").

Waits for a started run to settle by reading the real SSE stream
(`GET /agent-runs/{runId}/events`) rather than sleeping/polling — the same mechanism a real
client would use, and it exercises that endpoint for real in the process.

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
async def ready_task_and_context_package(client: TestClient, tmp_path) -> dict[str, str]:
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

    return {"project_id": project["id"], "task_id": task["id"], "context_package_id": package["job_id"]}


def _read_sse_events(client: TestClient, run_id: str) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    current_event: str | None = None
    with client.stream("GET", f"/api/v1/agent-runs/{run_id}/events") as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event:"):
                current_event = line.removeprefix("event:").strip()
            elif line.startswith("data:") and current_event is not None:
                events.append((current_event, line.removeprefix("data:").strip()))
                current_event = None
    return events


async def test_register_agent_assign_and_run_to_awaiting_approval(
    client: TestClient, ready_task_and_context_package: dict[str, str]
) -> None:
    agent = client.post(
        "/api/v1/agents",
        json={"name": "CodingAgent", "agent_type": "coding", "version": "1.0.0"},
    ).json()

    assign_response = client.post(
        f"/api/v1/tasks/{ready_task_and_context_package['task_id']}/assign",
        json={"agent_id": agent["id"]},
    )
    assert assign_response.status_code == 200
    assert assign_response.json()["assigned_agent_id"] == agent["id"]

    run_response = client.post(
        f"/api/v1/tasks/{ready_task_and_context_package['task_id']}/runs",
        json={
            "provider": "claude",
            "model_name": "claude-x",
            "context_package_id": ready_task_and_context_package["context_package_id"],
        },
    )
    assert run_response.status_code == 202
    run_id = run_response.json()["agent_run_id"]

    events = _read_sse_events(client, run_id)
    assert events[-1][0] == "agent_run.persisted"

    run = client.get(f"/api/v1/agent-runs/{run_id}").json()
    assert run["status"] == "succeeded"

    task = client.get(
        f"/api/v1/tasks/{ready_task_and_context_package['task_id']}/context-packages"
    )
    assert task.status_code == 200  # sanity: task_id round-trips through context_builder too


async def test_full_review_lifecycle_approve_and_merge(
    client: TestClient, ready_task_and_context_package: dict[str, str]
) -> None:
    task_id = ready_task_and_context_package["task_id"]
    agent = client.post(
        "/api/v1/agents", json={"name": "CodingAgent2", "agent_type": "coding", "version": "1.0.0"}
    ).json()
    client.post(f"/api/v1/tasks/{task_id}/assign", json={"agent_id": agent["id"]})
    run_id = client.post(
        f"/api/v1/tasks/{task_id}/runs",
        json={
            "provider": "claude",
            "model_name": "claude-x",
            "context_package_id": ready_task_and_context_package["context_package_id"],
        },
    ).json()["agent_run_id"]
    _read_sse_events(client, run_id)

    approve_response = client.post(f"/api/v1/tasks/{task_id}/approve", json={"comment": "lgtm"})
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"

    merge_response = client.post(f"/api/v1/tasks/{task_id}/merge")
    assert merge_response.status_code == 200
    assert merge_response.json()["status"] == "merged"


async def test_start_run_requires_assignment(
    client: TestClient, ready_task_and_context_package: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/tasks/{ready_task_and_context_package['task_id']}/runs",
        json={
            "provider": "claude",
            "model_name": "claude-x",
            "context_package_id": ready_task_and_context_package["context_package_id"],
        },
    )
    assert response.status_code == 409


def test_get_run_404_when_missing(client: TestClient) -> None:
    response = client.get("/api/v1/agent-runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_register_agent_rejects_duplicate_name_version(client: TestClient) -> None:
    body = {"name": "DupAgent", "agent_type": "coding", "version": "1.0.0"}
    first = client.post("/api/v1/agents", json=body)
    assert first.status_code == 201

    second = client.post("/api/v1/agents", json=body)
    assert second.status_code == 409
