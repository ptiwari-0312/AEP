from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.projects.domain.models import Feature, FeatureStatus, Project
from aep.modules.projects.repository.feature_repository import FeatureRepository
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
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
async def project(session) -> Project:
    return await ProjectRepository(session).add(
        Project(id=uuid4(), name="AEP", slug="aep", owner_user_id=uuid4())
    )


async def test_add_and_get_by_id_round_trips(session, project: Project) -> None:
    repository = FeatureRepository(session)
    creator_id = uuid4()

    created = await repository.add(
        Feature(id=uuid4(), project_id=project.id, title="New screen", created_by=creator_id)
    )
    fetched = await repository.get_by_id(created.id)

    assert fetched is not None
    assert fetched.title == "New screen"
    assert fetched.project_id == project.id
    assert fetched.created_by == creator_id
    assert fetched.status == FeatureStatus.DRAFT


async def test_list_for_project_filters_by_status(session, project: Project) -> None:
    repository = FeatureRepository(session)
    await repository.add(Feature(id=uuid4(), project_id=project.id, title="A", created_by=uuid4()))
    in_progress = await repository.add(
        Feature(id=uuid4(), project_id=project.id, title="B", created_by=uuid4())
    )
    in_progress.status = FeatureStatus.IN_PROGRESS
    await repository.update(in_progress)

    all_features = await repository.list_for_project(project.id)
    assert len(all_features) == 2

    only_in_progress = await repository.list_for_project(project.id, status=FeatureStatus.IN_PROGRESS)
    assert len(only_in_progress) == 1
    assert only_in_progress[0].title == "B"


async def test_update_persists_status_transition(session, project: Project) -> None:
    repository = FeatureRepository(session)
    feature = await repository.add(
        Feature(id=uuid4(), project_id=project.id, title="A", created_by=uuid4())
    )

    feature.status = FeatureStatus.IN_PROGRESS
    updated = await repository.update(feature)

    assert updated.status == FeatureStatus.IN_PROGRESS
    reloaded = await repository.get_by_id(feature.id)
    assert reloaded is not None
    assert reloaded.status == FeatureStatus.IN_PROGRESS
