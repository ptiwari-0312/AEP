"""End-to-end test of the Context Builder through the real HTTP API, including its calls across
the module boundary into `task_memory`'s `TaskService` and `projects`'
`FeatureService`/`ProjectService` (docs/architecture/02-repo-design.md §2: `tests/integration` is
"cross-module, real DB").

Indexing has no HTTP endpoint (docs/architecture/04-api-design.md §4 has none — see this
module's README), so test fixtures seed `source_documents` by calling `SourceDocumentIndexer`
directly against the same SQLite database the API's `TestClient` is using, then exercise
generation/listing entirely through real HTTP requests.

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
def project_and_task(client: TestClient) -> dict[str, str]:
    project = client.post("/api/v1/projects", json={"name": "AEP", "slug": "aep"}).json()
    feature = client.post(
        f"/api/v1/projects/{project['id']}/features", json={"title": "Add login"}
    ).json()
    task = client.post(
        f"/api/v1/features/{feature['id']}/tasks",
        json={
            "title": "Implement password reset",
            "task_type": "code",
            "description": "Add a password reset endpoint.",
        },
    ).json()
    return {"project_id": project["id"], "feature_id": feature["id"], "task_id": task["id"]}


async def _index(project_id: str, root_path) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        indexer = SourceDocumentIndexer(SourceDocumentRepository(session))
        await indexer.index_directory(UUID(project_id), root_path)
        await session.commit()


def test_generate_context_package_requires_a_real_task(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks/00000000-0000-0000-0000-000000000000/context-packages",
        json={"max_tokens": 1000},
    )
    assert response.status_code == 404
    assert response.json()["type"] == "https://aep.dev/errors/NotFoundError"


def test_generate_context_package_rejects_non_positive_max_tokens(
    client: TestClient, project_and_task: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/tasks/{project_and_task['task_id']}/context-packages", json={"max_tokens": 0}
    )
    assert response.status_code == 422


async def test_full_generation_and_listing_lifecycle(
    client: TestClient, project_and_task: dict[str, str], tmp_path
) -> None:
    (tmp_path / "CODING_STANDARDS.md").write_text("# Coding Standards\nUse snake_case.\n")
    (tmp_path / "auth.py").write_text(
        "def reset_password(user):\n    return send_reset_email(user)\n"
    )
    await _index(project_and_task["project_id"], tmp_path)

    generate_response = client.post(
        f"/api/v1/tasks/{project_and_task['task_id']}/context-packages",
        json={"max_tokens": 100_000},
    )
    assert generate_response.status_code == 202
    body = generate_response.json()
    assert body["status"] == "completed"
    context_package_id = body["job_id"]

    get_response = client.get(f"/api/v1/context-packages/{context_package_id}")
    assert get_response.status_code == 200
    assert get_response.json()["task_id"] == project_and_task["task_id"]
    assert get_response.json()["token_count"] > 0

    history_response = client.get(
        f"/api/v1/tasks/{project_and_task['task_id']}/context-packages"
    )
    assert history_response.status_code == 200
    assert history_response.json()["total"] == 1

    sources_response = client.get(f"/api/v1/context-packages/{context_package_id}/sources")
    assert sources_response.status_code == 200
    sources_body = sources_response.json()
    assert sources_body["total"] == 2
    assert all(item["included"] for item in sources_body["items"])

    documents_response = client.get(
        f"/api/v1/projects/{project_and_task['project_id']}/source-documents"
    )
    assert documents_response.status_code == 200
    assert documents_response.json()["total"] == 2


def test_get_context_package_404_when_missing(client: TestClient) -> None:
    response = client.get("/api/v1/context-packages/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_source_documents_requires_a_real_project(client: TestClient) -> None:
    response = client.get(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/source-documents"
    )
    assert response.status_code == 404
