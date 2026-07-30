from __future__ import annotations

from uuid import uuid4

import pytest

from aep.core.config import get_settings
from aep.core.db import Base, get_engine, get_session_factory
from aep.modules.metrics.domain.models import Metric
from aep.modules.metrics.repository.metric_repository import MetricRepository


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
        yield MetricRepository(session)


async def test_add_round_trips(repository: MetricRepository) -> None:
    entity_id = uuid4()
    metric = Metric(
        id=uuid4(),
        metric_name="agent_run.cost_usd",
        entity_type="agent_run",
        entity_id=entity_id,
        value=0.05,
        unit="usd",
    )

    created = await repository.add(metric)

    assert created.entity_id == entity_id
    assert created.recorded_at is not None


async def test_list_for_query_filters_by_metric_name_and_paginates(
    repository: MetricRepository,
) -> None:
    entity_id = uuid4()
    for i in range(3):
        await repository.add(
            Metric(
                id=uuid4(),
                metric_name="agent_run.cost_usd",
                entity_type="agent_run",
                entity_id=entity_id,
                value=float(i),
            )
        )
    await repository.add(
        Metric(
            id=uuid4(),
            metric_name="other.metric",
            entity_type="agent_run",
            entity_id=entity_id,
            value=1.0,
        )
    )

    first_page, cursor, has_more = await repository.list_for_query(
        metric_name="agent_run.cost_usd", limit=2
    )
    assert len(first_page) == 2
    assert has_more is True
    assert cursor is not None

    second_page, cursor2, has_more2 = await repository.list_for_query(
        metric_name="agent_run.cost_usd", limit=2, cursor=cursor
    )
    assert len(second_page) == 1
    assert has_more2 is False
    assert cursor2 is None


async def test_list_for_query_filters_by_entity(repository: MetricRepository) -> None:
    entity_a = uuid4()
    entity_b = uuid4()
    await repository.add(
        Metric(id=uuid4(), metric_name="m", entity_type="agent_run", entity_id=entity_a, value=1.0)
    )
    await repository.add(
        Metric(id=uuid4(), metric_name="m", entity_type="agent_run", entity_id=entity_b, value=2.0)
    )

    scoped, _, _ = await repository.list_for_query(
        metric_name="m", entity_type="agent_run", entity_id=entity_a
    )

    assert len(scoped) == 1
    assert scoped[0].entity_id == entity_a


async def test_list_values_grouped_by_day(repository: MetricRepository) -> None:
    entity_id = uuid4()
    for value in (1.0, 2.0, 3.0):
        await repository.add(
            Metric(id=uuid4(), metric_name="m", entity_type="agent_run", entity_id=entity_id, value=value)
        )

    grouped = await repository.list_values_grouped_by_day(metric_name="m")

    assert len(grouped) == 1  # all recorded "now", so one day bucket
    (values,) = grouped.values()
    assert sorted(values) == [1.0, 2.0, 3.0]


async def test_list_values_grouped_by_entity(repository: MetricRepository) -> None:
    project_a = uuid4()
    project_b = uuid4()
    await repository.add(
        Metric(id=uuid4(), metric_name="m", entity_type="project", entity_id=project_a, value=1.0)
    )
    await repository.add(
        Metric(id=uuid4(), metric_name="m", entity_type="project", entity_id=project_a, value=3.0)
    )
    await repository.add(
        Metric(id=uuid4(), metric_name="m", entity_type="project", entity_id=project_b, value=5.0)
    )
    await repository.add(
        Metric(id=uuid4(), metric_name="m", entity_type="agent", entity_id=uuid4(), value=99.0)
    )

    grouped = await repository.list_values_grouped_by_entity(metric_name="m", entity_type="project")

    assert grouped[str(project_a)] == [1.0, 3.0]
    assert grouped[str(project_b)] == [5.0]
    assert len(grouped) == 2


async def test_list_values_grouped_by_metric_name(repository: MetricRepository) -> None:
    project_id = uuid4()
    await repository.add(
        Metric(id=uuid4(), metric_name="cost_usd", entity_type="project", entity_id=project_id, value=1.0)
    )
    await repository.add(
        Metric(
            id=uuid4(), metric_name="duration_ms", entity_type="project", entity_id=project_id, value=500.0
        )
    )
    await repository.add(
        Metric(id=uuid4(), metric_name="cost_usd", entity_type="project", entity_id=uuid4(), value=99.0)
    )

    grouped = await repository.list_values_grouped_by_metric_name(
        entity_type="project", entity_id=project_id
    )

    assert grouped["cost_usd"] == [1.0]
    assert grouped["duration_ms"] == [500.0]
