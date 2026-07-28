"""The BaseEvaluator contract (docs/architecture/07-evaluation-framework.md §2)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, ClassVar, final

from .runtime import EventPublisher, MetricsSink, NullEventPublisher, NullMetricsSink
from .types import (
    AgentRunContext,
    EvaluationReport,
    EvaluationStatus,
    EvaluatorInput,
    EvaluatorOutput,
    EvaluatorOutputStatus,
    EvaluatorType,
    MetricScore,
)

_FINAL_METHOD_NAMES = ("run", "resume_from_external")


class BaseEvaluator(ABC):
    """Every evaluator type subclasses this and implements exactly the four hook methods below
    — `prepare`, `execute`, `score`, `report` — deliberately the same four-phase shape as the
    Agent SDK's `BaseAgent` (`plan`/`execute`/`evaluate`/`report`), so the two plugin systems
    read the same way (ADR-EV1, docs/architecture/07-evaluation-framework.md §2). `run` and
    `resume_from_external` are final and enforced at class-definition time, same as
    BaseAgent's final methods.
    """

    evaluator_type: ClassVar[EvaluatorType]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for method_name in _FINAL_METHOD_NAMES:
            if getattr(cls, method_name) is not getattr(BaseEvaluator, method_name):
                raise TypeError(
                    f"{cls.__name__} may not override BaseEvaluator.{method_name}() — it is "
                    f"final by design (docs/architecture/07-evaluation-framework.md §2)."
                )

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        event_publisher: EventPublisher | None = None,
        metrics_sink: MetricsSink | None = None,
    ) -> None:
        if not hasattr(self, "evaluator_type"):
            raise TypeError(f"{type(self).__name__} must set a class-level evaluator_type")
        self.config: dict[str, Any] = config or {}
        self.log = logging.getLogger(f"aep.evaluator.{self.evaluator_type.value}")
        self._event_publisher: EventPublisher = event_publisher or NullEventPublisher()
        self._metrics_sink: MetricsSink = metrics_sink or NullMetricsSink()

    # ---- hook methods: implemented by subclasses ------------------------------------------

    @abstractmethod
    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        """Gather whatever execute() needs: fixtures, dataset refs, threshold config — the
        phase worth caching/reusing independent of execute() itself."""

    @abstractmethod
    async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
        """Run the actual evaluation (a subprocess, an LLM call, a remote platform call).
        Return `status=PENDING_EXTERNAL` with `external_ref_id` set if scoring happens
        asynchronously on an external platform, e.g. Braintrust/Langfuse
        (docs/architecture/07-evaluation-framework.md §5)."""

    @abstractmethod
    async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
        """Normalize raw output into comparable MetricScores."""

    @abstractmethod
    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        """Produce the final summary, including the overall `status` — an evaluator-specific
        judgment (e.g. all-scores-must-pass vs. a weighted rule), not something computed
        generically by run(). run() fills in `evaluator_type`/`started_at`/`completed_at`
        afterward."""

    # ---- lifecycle methods: final, not overridable ----------------------------------------

    @final
    def emit_metric(self, metric_name: str, value: float, **tags: Any) -> None:
        """Emit an evaluator-specific metric, additive to the standard set run() already emits
        automatically."""
        self._metrics_sink.emit(
            metric_name, value, evaluator_type=self.evaluator_type.value, **tags
        )

    @final
    async def run(self, agent_run: AgentRunContext) -> EvaluationReport:
        """The entry point the Evaluation Runner calls. Drives
        prepare -> execute -> (score -> report), or returns a `running` placeholder if
        execute() reports `PENDING_EXTERNAL` — in that case score()/report() are deferred to
        resume_from_external() (docs/architecture/07-evaluation-framework.md §2, §5).
        Evaluators have no retry policy of their own (unlike agents, docs/architecture/05-
        agent-sdk.md §6): a failed evaluation is reported as ERROR, and re-run — if desired —
        by calling run() again from outside."""
        started_at = datetime.now(UTC)
        try:
            await self._publish(agent_run, "evaluation.preparing", {})
            self.log.info("evaluation preparing: agent_run_id=%s", agent_run.agent_run_id)
            evaluator_input = await self.prepare(agent_run)

            await self._publish(agent_run, "evaluation.executing", {})
            self.log.info("evaluation executing: agent_run_id=%s", agent_run.agent_run_id)
            output = await self.execute(evaluator_input)

            if output.status == EvaluatorOutputStatus.PENDING_EXTERNAL:
                self.log.info(
                    "evaluation pending external result: agent_run_id=%s external_ref_id=%s",
                    agent_run.agent_run_id,
                    output.external_ref_id,
                )
                await self._publish(
                    agent_run,
                    "evaluation.pending_external",
                    {"external_ref_id": output.external_ref_id},
                )
                return EvaluationReport(
                    evaluator_type=self.evaluator_type,
                    status=EvaluationStatus.RUNNING,
                    pending_external_ref_id=output.external_ref_id,
                    started_at=started_at,
                )

            return await self._score_and_report(agent_run, output, started_at)
        except Exception as exc:  # noqa: BLE001 - the run() boundary's job is to classify and
            # report on whatever a hook raised (docs/architecture/09-engineering-standards.md §6).
            return await self._error_report(agent_run, exc, started_at)

    @final
    async def resume_from_external(
        self,
        agent_run: AgentRunContext,
        output: EvaluatorOutput,
        *,
        started_at: datetime | None = None,
    ) -> EvaluationReport:
        """Called by the webhook handler or polling fallback once an external platform
        (Braintrust/Langfuse) delivers its result — resumes at score() -> report()
        (docs/architecture/07-evaluation-framework.md §5). `output.status` must already be
        COMPLETED."""
        if output.status != EvaluatorOutputStatus.COMPLETED:
            raise ValueError("resume_from_external() requires a COMPLETED EvaluatorOutput")
        effective_started_at = started_at or datetime.now(UTC)
        try:
            return await self._score_and_report(agent_run, output, effective_started_at)
        except Exception as exc:  # noqa: BLE001 - see run()'s matching comment
            return await self._error_report(agent_run, exc, effective_started_at)

    # ---- internal helpers -------------------------------------------------------------------

    async def _score_and_report(
        self, agent_run: AgentRunContext, output: EvaluatorOutput, started_at: datetime
    ) -> EvaluationReport:
        await self._publish(agent_run, "evaluation.scoring", {})
        scores = await self.score(output)

        await self._publish(agent_run, "evaluation.reporting", {})
        report = await self.report(scores)
        report = report.model_copy(
            update={
                "evaluator_type": self.evaluator_type,
                "started_at": started_at,
                "completed_at": datetime.now(UTC),
            }
        )
        self.log.info(
            "evaluation completed: agent_run_id=%s status=%s",
            agent_run.agent_run_id,
            report.status.value,
        )
        await self._publish(agent_run, "evaluation.completed", {"status": report.status.value})
        self._emit_standard_metrics(report)
        return report

    async def _error_report(
        self, agent_run: AgentRunContext, exc: Exception, started_at: datetime
    ) -> EvaluationReport:
        self.log.error(
            "evaluation error: agent_run_id=%s error=%s", agent_run.agent_run_id, exc
        )
        await self._publish(agent_run, "evaluation.error", {"error": str(exc)})
        report = EvaluationReport(
            evaluator_type=self.evaluator_type,
            status=EvaluationStatus.ERROR,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            error=str(exc),
        )
        self._emit_standard_metrics(report)
        return report

    async def _publish(
        self, agent_run: AgentRunContext, event_type: str, payload: dict[str, Any]
    ) -> None:
        envelope: dict[str, Any] = {
            "agent_run_id": str(agent_run.agent_run_id),
            "task_id": str(agent_run.task_id),
            "evaluator_type": self.evaluator_type.value,
            **payload,
        }
        await self._event_publisher.publish(event_type, envelope)

    def _emit_standard_metrics(self, report: EvaluationReport) -> None:
        tags = {"evaluator_type": self.evaluator_type.value}
        if report.started_at is not None and report.completed_at is not None:
            duration_ms = (report.completed_at - report.started_at).total_seconds() * 1000
            self._metrics_sink.emit("evaluation.duration_ms", duration_ms, **tags)
        for metric_score in report.scores:
            self._metrics_sink.emit(
                f"evaluation.score.{metric_score.metric_name}", metric_score.score, **tags
            )
        if report.status in (EvaluationStatus.PASSED, EvaluationStatus.FAILED):
            self._metrics_sink.emit(
                "evaluation.passed",
                1.0 if report.status == EvaluationStatus.PASSED else 0.0,
                **tags,
            )
