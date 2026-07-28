from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.projects.domain.errors import (
    FeatureNotFoundError,
    IllegalFeatureStatusTransitionError,
    ProjectNotFoundError,
)
from aep.modules.projects.domain.models import FeatureStatus
from aep.modules.projects.repository.feature_repository import FeatureRepository
from aep.modules.projects.repository.project_repository import ProjectRepository
from aep.modules.projects.services.feature_service import FeatureService
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
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
async def project(session):
    return await ProjectService(ProjectRepository(session)).create_project(
        name="AEP", slug="aep", owner_user_id=uuid4()
    )


@pytest.fixture
def feature_service(session) -> FeatureService:
    return FeatureService(FeatureRepository(session), ProjectRepository(session))


async def test_create_feature_succeeds(feature_service: FeatureService, project) -> None:
    feature = await feature_service.create_feature(
        project_id=project.id, title="New screen", created_by=uuid4()
    )

    assert feature.title == "New screen"
    assert feature.status == FeatureStatus.DRAFT


async def test_create_feature_raises_when_project_missing(feature_service: FeatureService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await feature_service.create_feature(project_id=uuid4(), title="X", created_by=uuid4())


async def test_get_feature_raises_not_found(feature_service: FeatureService) -> None:
    with pytest.raises(FeatureNotFoundError):
        await feature_service.get_feature(uuid4())


async def test_transition_status_follows_legal_edge(feature_service: FeatureService, project) -> None:
    feature = await feature_service.create_feature(project_id=project.id, title="X", created_by=uuid4())

    updated = await feature_service.transition_status(feature.id, to_status=FeatureStatus.IN_PROGRESS)

    assert updated.status == FeatureStatus.IN_PROGRESS


async def test_transition_status_rejects_illegal_edge(feature_service: FeatureService, project) -> None:
    feature = await feature_service.create_feature(project_id=project.id, title="X", created_by=uuid4())

    with pytest.raises(IllegalFeatureStatusTransitionError):
        await feature_service.transition_status(feature.id, to_status=FeatureStatus.DONE)


async def test_list_features_for_project_raises_when_project_missing(feature_service: FeatureService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await feature_service.list_features_for_project(uuid4())
