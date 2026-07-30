"""SQLAlchemy ORM model for the Metrics Service's table (docs/architecture/03-db-design.md §18).
Lives here, not in `domain/`, so `domain/` stays framework-free
(docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from aep.core.db import Base, utcnow


class MetricModel(Base):
    __tablename__ = "metrics"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Polymorphic by design (DB design §18), same convention as `audit_events` — no FK, this
    # module has no fixed opinion on which table `entity_id` points into.
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    value: Mapped[float] = mapped_column(Numeric(18, 6, asdecimal=False), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        Index("ix_metrics_metric_name_recorded_at", "metric_name", "recorded_at"),
        Index("ix_metrics_entity_type_entity_id", "entity_type", "entity_id"),
    )
