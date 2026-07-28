from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.projects.domain.models import Project, ProjectStatus
from aep.modules.projects.repository.project_repository import ProjectRepository


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
async def repository():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield ProjectRepository(session)


async def test_add_and_get_by_id_round_trips(repository: ProjectRepository) -> None:
    owner_id = uuid4()
    project = Project(id=uuid4(), name="AEP", slug="aep", owner_user_id=owner_id)

    created = await repository.add(project)

    fetched = await repository.get_by_id(created.id)
    assert fetched is not None
    assert fetched.name == "AEP"
    assert fetched.slug == "aep"
    assert fetched.owner_user_id == owner_id
    assert fetched.status == ProjectStatus.ACTIVE
    assert fetched.created_at is not None


async def test_get_by_slug_finds_existing_project(repository: ProjectRepository) -> None:
    await repository.add(Project(id=uuid4(), name="AEP", slug="aep", owner_user_id=uuid4()))

    found = await repository.get_by_slug("aep")
    assert found is not None
    assert found.name == "AEP"

    assert await repository.get_by_slug("does-not-exist") is None


async def test_list_filters_by_status_and_paginates(repository: ProjectRepository) -> None:
    owner_id = uuid4()
    for i in range(3):
        await repository.add(
            Project(id=uuid4(), name=f"Project {i}", slug=f"project-{i}", owner_user_id=owner_id)
        )
    archived = Project(
        id=uuid4(), name="Old", slug="old", owner_user_id=owner_id, status=ProjectStatus.ARCHIVED
    )
    await repository.add(archived)

    active_projects, total = await repository.list(status=ProjectStatus.ACTIVE, limit=2, offset=0)
    assert total == 3
    assert len(active_projects) == 2

    all_for_owner, total_for_owner = await repository.list(owner_user_id=owner_id, limit=10)
    assert total_for_owner == 4
    assert len(all_for_owner) == 4


async def test_list_name_search_is_case_insensitive(repository: ProjectRepository) -> None:
    await repository.add(Project(id=uuid4(), name="Agentic Platform", slug="ap", owner_user_id=uuid4()))

    found, total = await repository.list(name_contains="agentic")
    assert total == 1
    assert found[0].name == "Agentic Platform"


async def test_update_persists_changes(repository: ProjectRepository) -> None:
    project = await repository.add(
        Project(id=uuid4(), name="Original", slug="original", owner_user_id=uuid4())
    )

    project.name = "Renamed"
    project.status = ProjectStatus.ARCHIVED
    updated = await repository.update(project)

    assert updated.name == "Renamed"
    assert updated.status == ProjectStatus.ARCHIVED

    reloaded = await repository.get_by_id(project.id)
    assert reloaded is not None
    assert reloaded.name == "Renamed"
    assert reloaded.status == ProjectStatus.ARCHIVED
