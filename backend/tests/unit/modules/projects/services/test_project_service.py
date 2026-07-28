from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.projects.domain.errors import (
    ProjectAlreadyArchivedError,
    ProjectNotFoundError,
    SlugAlreadyExistsError,
)
from aep.modules.projects.domain.models import ProjectStatus
from aep.modules.projects.repository.project_repository import ProjectRepository
from aep.modules.projects.services.project_service import ProjectService


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
async def service():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield ProjectService(ProjectRepository(session))


async def test_create_project_succeeds(service: ProjectService) -> None:
    project = await service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())

    assert project.name == "AEP"
    assert project.status == ProjectStatus.ACTIVE


async def test_create_project_rejects_duplicate_slug(service: ProjectService) -> None:
    await service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())

    with pytest.raises(SlugAlreadyExistsError):
        await service.create_project(name="AEP Again", slug="aep", owner_user_id=uuid4())


async def test_get_project_raises_not_found(service: ProjectService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.get_project(uuid4())


async def test_update_project_changes_name_and_description(service: ProjectService) -> None:
    project = await service.create_project(name="Original", slug="original", owner_user_id=uuid4())

    updated = await service.update_project(project.id, name="Renamed", description="new description")

    assert updated.name == "Renamed"
    assert updated.description == "new description"


async def test_archive_project_transitions_to_archived(service: ProjectService) -> None:
    project = await service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())

    archived = await service.archive_project(project.id)

    assert archived.status == ProjectStatus.ARCHIVED


async def test_archive_project_twice_raises_already_archived(service: ProjectService) -> None:
    project = await service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())
    await service.archive_project(project.id)

    with pytest.raises(ProjectAlreadyArchivedError):
        await service.archive_project(project.id)


async def test_attach_repository_sets_git_repository_id(service: ProjectService) -> None:
    project = await service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())
    repo_id = uuid4()

    updated = await service.attach_repository(project.id, git_repository_id=repo_id)

    assert updated.git_repository_id == repo_id


async def test_list_projects_respects_filters(service: ProjectService) -> None:
    owner_id = uuid4()
    await service.create_project(name="A", slug="a", owner_user_id=owner_id)
    await service.create_project(name="B", slug="b", owner_user_id=uuid4())

    projects, total = await service.list_projects(owner_user_id=owner_id)

    assert total == 1
    assert projects[0].name == "A"
