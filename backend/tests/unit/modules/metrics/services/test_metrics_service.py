from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.metrics.domain.errors import (
    ProjectNotFoundError,
    UnsupportedAggregationError,
    UnsupportedGroupByError,
)
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


@pytest.fixture
async def session():
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


@pytest.fixture
def project_service(session) -> ProjectService:
    return ProjectService(ProjectRepository(session))


@pytest.fixture
def service(session, project_service) -> MetricsService:
    return MetricsService(MetricRepository(session), project_service)


@pytest.fixture
async def project(project_service):
    return await project_service.create_project(name="AEP", slug="aep", owner_user_id=uuid4())


async def test_record_metric_persists_it(service: MetricsService) -> None:
    entity_id = uuid4()

    metric = await service.record_metric(
        metric_name="agent_run.cost_usd", entity_type="agent_run", entity_id=entity_id, value=0.05
    )

    fetched, _, _ = await service.list_metrics(metric_name="agent_run.cost_usd")
    assert fetched[0].id == metric.id


async def test_get_summary_rejects_unsupported_group_by(service: MetricsService) -> None:
    with pytest.raises(UnsupportedGroupByError):
        await service.get_summary(metric_name="m", group_by="provider", agg="sum")


async def test_get_summary_rejects_unsupported_agg(service: MetricsService) -> None:
    with pytest.raises(UnsupportedAggregationError):
        await service.get_summary(metric_name="m", group_by="day", agg="median")


async def test_get_summary_group_by_day_sum(service: MetricsService) -> None:
    entity_id = uuid4()
    for value in (1.0, 2.0, 3.0):
        await service.record_metric(
            metric_name="m", entity_type="agent_run", entity_id=entity_id, value=value
        )

    summary = await service.get_summary(metric_name="m", group_by="day", agg="sum")

    assert len(summary.buckets) == 1
    assert summary.buckets[0].value == 6.0


async def test_get_summary_group_by_project_avg(service: MetricsService) -> None:
    project_a = uuid4()
    project_b = uuid4()
    for value in (2.0, 4.0):
        await service.record_metric(
            metric_name="m", entity_type="project", entity_id=project_a, value=value
        )
    await service.record_metric(metric_name="m", entity_type="project", entity_id=project_b, value=10.0)

    summary = await service.get_summary(metric_name="m", group_by="project", agg="avg")

    buckets_by_key = {b.key: b.value for b in summary.buckets}
    assert buckets_by_key[str(project_a)] == 3.0
    assert buckets_by_key[str(project_b)] == 10.0


async def test_get_summary_p95_computed_over_bucket_values(service: MetricsService) -> None:
    entity_id = uuid4()
    for value in range(1, 21):  # 1..20
        await service.record_metric(
            metric_name="m", entity_type="agent", entity_id=entity_id, value=float(value)
        )

    summary = await service.get_summary(metric_name="m", group_by="agent", agg="p95")

    # nearest-rank p95 of 1..20 (n=20): ceil(0.95*20)-1 = 18 -> sorted_values[18] == 19
    assert summary.buckets[0].value == 19.0


async def test_get_project_summary_rolls_up_by_metric_name(
    service: MetricsService, project
) -> None:
    await service.record_metric(
        metric_name="cost_usd", entity_type="project", entity_id=project.id, value=1.0
    )
    await service.record_metric(
        metric_name="cost_usd", entity_type="project", entity_id=project.id, value=3.0
    )

    summary = await service.get_project_summary(project.id)

    entry = next(e for e in summary.metrics if e.metric_name == "cost_usd")
    assert entry.sum == 4.0
    assert entry.avg == 2.0
    assert entry.count == 2


async def test_get_project_summary_raises_when_project_missing(service: MetricsService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await service.get_project_summary(uuid4())
