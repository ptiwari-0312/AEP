"""Data access for `metrics` (docs/architecture/03-db-design.md §18). Cursor-paginated per
docs/architecture/04-api-design.md §0.3, which names "metrics" explicitly as one of the
high-volume/append-only collections.

The grouped-listing methods return raw values per bucket (not a pre-aggregated SQL sum/avg) so
`MetricsService` can compute `sum`/`avg`/`p95` uniformly in Python across all three — `p95` has
no portable SQL expression across SQLite (this project's test backend) and Postgres (production)
short of Postgres-specific `percentile_cont`, so pushing only *some* aggregations down to SQL and
computing others in Python would mean two different code paths computing "the same kind of
number." See `services/metrics_service.py`'s docstring for the scaling caveat this implies.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aep.core.pagination import decode_cursor, encode_cursor

from ..domain.models import Metric
from .models import MetricModel


class MetricRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, metric: Metric) -> Metric:
        model = _to_model(metric)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return _to_domain(model)

    async def list_for_query(
        self,
        *,
        metric_name: str,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        recorded_at_from: datetime | None = None,
        recorded_at_to: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[Metric], str | None, bool]:
        query = select(MetricModel).where(MetricModel.metric_name == metric_name)
        query = _apply_common_filters(query, entity_type, entity_id, recorded_at_from, recorded_at_to)
        if cursor is not None:
            cursor_recorded_at, cursor_id = decode_cursor(cursor)
            query = query.where(
                or_(
                    MetricModel.recorded_at > cursor_recorded_at,
                    and_(
                        MetricModel.recorded_at == cursor_recorded_at, MetricModel.id > cursor_id
                    ),
                )
            )
        query = query.order_by(MetricModel.recorded_at.asc(), MetricModel.id.asc()).limit(limit + 1)

        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            encode_cursor(rows[-1].recorded_at, rows[-1].id) if has_more and rows else None
        )
        return [_to_domain(m) for m in rows], next_cursor, has_more

    async def list_values_grouped_by_day(
        self,
        *,
        metric_name: str,
        recorded_at_from: datetime | None = None,
        recorded_at_to: datetime | None = None,
    ) -> dict[str, list[float]]:
        day_bucket = func.date(MetricModel.recorded_at)
        query = select(day_bucket, MetricModel.value).where(MetricModel.metric_name == metric_name)
        query = _apply_common_filters(query, None, None, recorded_at_from, recorded_at_to)
        result = await self._session.execute(query)
        return _group_rows(result.all())

    async def list_values_grouped_by_entity(
        self,
        *,
        metric_name: str,
        entity_type: str,
        recorded_at_from: datetime | None = None,
        recorded_at_to: datetime | None = None,
    ) -> dict[str, list[float]]:
        query = select(MetricModel.entity_id, MetricModel.value).where(
            MetricModel.metric_name == metric_name, MetricModel.entity_type == entity_type
        )
        query = _apply_common_filters(query, None, None, recorded_at_from, recorded_at_to)
        result = await self._session.execute(query)
        return _group_rows([(str(entity_id), value) for entity_id, value in result.all()])

    async def list_values_grouped_by_metric_name(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        recorded_at_from: datetime | None = None,
        recorded_at_to: datetime | None = None,
    ) -> dict[str, list[float]]:
        query = select(MetricModel.metric_name, MetricModel.value).where(
            MetricModel.entity_type == entity_type, MetricModel.entity_id == entity_id
        )
        query = _apply_common_filters(query, None, None, recorded_at_from, recorded_at_to)
        result = await self._session.execute(query)
        return _group_rows(result.all())


def _apply_common_filters(query, entity_type, entity_id, recorded_at_from, recorded_at_to):
    if entity_type is not None:
        query = query.where(MetricModel.entity_type == entity_type)
    if entity_id is not None:
        query = query.where(MetricModel.entity_id == entity_id)
    if recorded_at_from is not None:
        query = query.where(MetricModel.recorded_at >= recorded_at_from)
    if recorded_at_to is not None:
        query = query.where(MetricModel.recorded_at <= recorded_at_to)
    return query


def _group_rows(rows: Sequence[Row[Any] | tuple[Any, float]]) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    for key, value in rows:
        grouped.setdefault(str(key), []).append(value)
    return grouped


def _to_domain(model: MetricModel) -> Metric:
    return Metric(
        id=model.id,
        metric_name=model.metric_name,
        entity_type=model.entity_type,
        entity_id=model.entity_id,
        value=model.value,
        unit=model.unit,
        recorded_at=model.recorded_at,
    )


def _to_model(metric: Metric) -> MetricModel:
    return MetricModel(
        id=metric.id,
        metric_name=metric.metric_name,
        entity_type=metric.entity_type,
        entity_id=metric.entity_id,
        value=metric.value,
        unit=metric.unit,
    )
