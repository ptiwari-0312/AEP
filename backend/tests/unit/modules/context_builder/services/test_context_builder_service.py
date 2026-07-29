"""End-to-end tests for the Context Builder pipeline against real collaborators: a real
SQLite-backed `task_memory.TaskService`/`projects.FeatureService`/`projects.ProjectService` (the
same cross-module composition `api/dependencies.py` wires), and real local files on disk indexed
by `SourceDocumentIndexer` — no mocks, matching this codebase's standing rule of testing against
real dependencies wherever one is free to construct.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.context_builder.domain.errors import (
    ProjectNotFoundError,
    TaskNotFoundError,
)
from aep.modules.context_builder.repository.context_package_repository import (
    ContextPackageRepository,
)
from aep.modules.context_builder.repository.context_package_source_repository import (
    ContextPackageSourceRepository,
)
from aep.modules.context_builder.repository.source_document_repository import (
    SourceDocumentRepository,
)
from aep.modules.context_builder.services.context_builder_service import (
    ContextBuilderService,
)
from aep.modules.context_builder.services.indexing import SourceDocumentIndexer
from aep.modules.projects.repository.feature_repository import FeatureRepository
from aep.modules.projects.repository.project_repository import ProjectRepository
from aep.modules.projects.services import FeatureService, ProjectService
from aep.modules.task_memory.domain.models import TaskType
from aep.modules.task_memory.repository.execution_history_repository import (
    ExecutionHistoryRepository,
)
from aep.modules.task_memory.repository.task_dependency_repository import (
    TaskDependencyRepository,
)
from aep.modules.task_memory.repository.task_repository import TaskRepository
from aep.modules.task_memory.services import TaskService


def _basename(uri: str) -> str:
    return uri.replace("\\", "/").split("/")[-1]


@pytest.fixture(autouse=True)
async def _sqlite_backed_db(tmp_path_factory, monkeypatch):
    db_path = tmp_path_factory.mktemp("db") / "test.db"
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
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
def project_service(session) -> ProjectService:
    return ProjectService(ProjectRepository(session))


@pytest.fixture
def feature_service(session) -> FeatureService:
    return FeatureService(FeatureRepository(session), ProjectRepository(session))


@pytest.fixture
def task_service(session, feature_service) -> TaskService:
    return TaskService(
        TaskRepository(session),
        TaskDependencyRepository(session),
        ExecutionHistoryRepository(session),
        feature_service,
    )


@pytest.fixture
def context_builder_service(session, task_service, feature_service, project_service) -> ContextBuilderService:
    return ContextBuilderService(
        SourceDocumentRepository(session),
        ContextPackageRepository(session),
        ContextPackageSourceRepository(session),
        task_service,
        feature_service,
        project_service,
    )


@pytest.fixture
def indexer(session) -> SourceDocumentIndexer:
    return SourceDocumentIndexer(SourceDocumentRepository(session))


@pytest.fixture
async def project(project_service):
    return await project_service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())


@pytest.fixture
async def feature(feature_service, project):
    return await feature_service.create_feature(
        project_id=project.id, title="Add login", created_by=uuid4()
    )


@pytest.fixture
async def task(task_service, feature):
    return await task_service.create_task(
        feature_id=feature.id,
        title="Implement password reset",
        task_type=TaskType.CODE,
        description="Add a password reset endpoint that emails a reset link.",
    )


async def test_generate_context_package_raises_when_task_missing(context_builder_service) -> None:
    with pytest.raises(TaskNotFoundError):
        await context_builder_service.generate_context_package(uuid4(), max_tokens=1000)


async def test_generate_context_package_persists_package_and_sources(
    context_builder_service, indexer, project, task, tmp_path
) -> None:
    (tmp_path / "CODING_STANDARDS.md").write_text("# Coding Standards\nUse snake_case.\n")
    (tmp_path / "auth.py").write_text(
        "def reset_password(user):\n    send_reset_email(user)\n    return True\n"
    )
    await indexer.index_directory(project.id, tmp_path)

    package = await context_builder_service.generate_context_package(task.id, max_tokens=100_000)

    assert package.task_id == task.id
    assert package.token_count > 0
    assert package.ranking_algorithm_version

    sources, total = await context_builder_service.list_context_package_sources(package.id)
    assert total == 2
    # Generous budget: everything indexed should fit and be included.
    assert all(s.included for s in sources)
    # Assemble's fixed section order (design doc §9): coding_standard (section 1) ranks ahead of
    # source_file (section 5) regardless of textual similarity to the task.
    ranks_by_uri_suffix = {_basename(s.uri): s.rank for s in sources}
    assert ranks_by_uri_suffix["CODING_STANDARDS.md"] < ranks_by_uri_suffix["auth.py"]


async def test_tiny_budget_excludes_some_documents(
    context_builder_service, indexer, project, task, tmp_path
) -> None:
    for i in range(5):
        (tmp_path / f"file_{i}.py").write_text(f"def f_{i}():\n    return {i}\n" * 20)
    await indexer.index_directory(project.id, tmp_path)

    package = await context_builder_service.generate_context_package(task.id, max_tokens=10)

    assert package.token_count <= 10
    sources, _ = await context_builder_service.list_context_package_sources(package.id)
    assert any(not s.included for s in sources)


async def test_pinned_source_document_is_prioritized_over_budget_fit(
    context_builder_service, indexer, project, task, tmp_path
) -> None:
    # Same two fixtures as the "more relevant content wins" test below: without pinning, and at
    # this same max_tokens=17 (each file's single chunk is ~17 tokens, so only one fits),
    # `reset.py` would win on its own real semantic_similarity score. Pinning `unrelated.py`
    # forces its score to 1.0, which should flip that outcome.
    (tmp_path / "reset.py").write_text(
        "def implement_password_reset(user):\n    return send_reset_link(user)\n"
    )
    (tmp_path / "unrelated.py").write_text(
        "def render_dashboard_widget(config):\n    return build_chart(config)\n"
    )
    documents = await indexer.index_directory(project.id, tmp_path)
    to_pin = next(d for d in documents if d.uri.endswith("unrelated.py"))

    package = await context_builder_service.generate_context_package(
        task.id, max_tokens=17, pinned_source_document_ids={to_pin.id}
    )

    sources, _ = await context_builder_service.list_context_package_sources(
        package.id, included=True
    )
    included_uris = {_basename(s.uri) for s in sources}
    assert "unrelated.py" in included_uris
    assert "reset.py" not in included_uris


async def test_exact_duplicate_content_is_counted_once(
    context_builder_service, indexer, project, task, tmp_path
) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    same_content = "def shared_helper():\n    return 1\n"
    (tmp_path / "a" / "helper.py").write_text(same_content)
    (tmp_path / "b" / "helper_copy.py").write_text(same_content)
    documents = await indexer.index_directory(project.id, tmp_path)
    assert len(documents) == 2  # both indexed as separate catalog entries...

    package = await context_builder_service.generate_context_package(task.id, max_tokens=100_000)

    # ...but only one is considered/persisted, since they share a content_hash (exact dedup,
    # design doc §5 tier 1).
    _sources, total = await context_builder_service.list_context_package_sources(package.id)
    assert total == 1


async def test_more_relevant_content_wins_under_a_constrained_budget(
    context_builder_service, indexer, project, task, tmp_path
) -> None:
    # `task` (see fixture above) is about "password reset". One file's content overlaps that
    # heavily; the other shares no words with it. Same doc_type, so doc_type_prior doesn't
    # distinguish them — only the real Jaccard-based semantic_similarity signal should.
    (tmp_path / "reset.py").write_text(
        "def implement_password_reset(user):\n    return send_reset_link(user)\n"
    )
    (tmp_path / "unrelated.py").write_text(
        "def render_dashboard_widget(config):\n    return build_chart(config)\n"
    )
    await indexer.index_directory(project.id, tmp_path)

    # Both files are single chunks of exactly 17 estimated tokens each (verified: len(text)//4)
    # — a budget of exactly 17 fits one, not both, so which one gets in is decided purely by
    # score, not by which happens to be shorter.
    package = await context_builder_service.generate_context_package(task.id, max_tokens=17)

    sources, _ = await context_builder_service.list_context_package_sources(
        package.id, included=True
    )
    included_uris = {_basename(s.uri) for s in sources}
    assert "reset.py" in included_uris
    assert "unrelated.py" not in included_uris


async def test_list_context_packages_for_task_raises_when_task_missing(
    context_builder_service,
) -> None:
    with pytest.raises(TaskNotFoundError):
        await context_builder_service.list_context_packages_for_task(uuid4())


async def test_list_context_packages_for_task_returns_history(
    context_builder_service, indexer, project, task, tmp_path
) -> None:
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    await indexer.index_directory(project.id, tmp_path)

    first = await context_builder_service.generate_context_package(task.id, max_tokens=100_000)
    second = await context_builder_service.generate_context_package(task.id, max_tokens=100_000)

    packages, total = await context_builder_service.list_context_packages_for_task(task.id)
    assert total == 2
    assert {p.id for p in packages} == {first.id, second.id}


async def test_list_source_documents_for_project_requires_real_project(
    context_builder_service,
) -> None:
    with pytest.raises(ProjectNotFoundError):
        await context_builder_service.list_source_documents_for_project(uuid4())


async def test_list_source_documents_for_project_returns_indexed_documents(
    context_builder_service, indexer, project, tmp_path
) -> None:
    (tmp_path / "a.py").write_text("def a():\n    return 1\n")
    (tmp_path / "b.py").write_text("def b():\n    return 2\n")
    await indexer.index_directory(project.id, tmp_path)

    documents, total = await context_builder_service.list_source_documents_for_project(project.id)

    assert total == 2
    assert len(documents) == 2
