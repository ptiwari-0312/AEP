"""SQLAlchemy ORM models for the Evaluation Framework's tables
(docs/architecture/03-db-design.md §14-15). Lives here, not in `domain/`, so `domain/` stays
framework-free (docs/architecture/02-repo-design.md §2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Boolean, Uuid

from aep.core.db import Base, utcnow

_EVALUATOR_TYPE_CHECK = (
    "evaluator_type IN ('deepeval','promptfoo','llm_judge','braintrust','langfuse','unit_test',"
    "'integration_test','security_scan','static_analysis','coverage','performance',"
    "'architecture_rules')"
)
_STATUS_CHECK = "status IN ('pending','running','passed','failed','error')"


class EvaluationModel(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # No FK to `agent_runs.id`: same cross-module `create_all()` ripple reason as every other
    # module's deferred FKs — `agent_runs` is owned by `orchestrator`.
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    evaluator_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        CheckConstraint(_EVALUATOR_TYPE_CHECK, name="ck_evaluations_evaluator_type"),
        CheckConstraint(_STATUS_CHECK, name="ck_evaluations_status"),
        Index("ix_evaluations_agent_run_id_evaluator_type", "agent_run_id", "evaluator_type"),
    )


class EvaluationResultModel(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Real FK: `evaluations` is owned by this same module.
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("evaluations.id", ondelete="CASCADE"), nullable=False
    )
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # asdecimal=False: same reasoning as context_builder's ContextPackageSourceModel.relevance_score
    # — the domain model uses `float`, and Decimal's extra precision buys nothing here.
    score: Mapped[float] = mapped_column(Numeric(6, 4, asdecimal=False), nullable=False)
    threshold: Mapped[float | None] = mapped_column(
        Numeric(6, 4, asdecimal=False), nullable=True
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        Index("ix_evaluation_results_evaluation_id", "evaluation_id"),
        Index("ix_evaluation_results_metric_name_passed", "metric_name", "passed"),
    )
