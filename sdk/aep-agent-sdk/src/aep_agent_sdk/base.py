"""The BaseAgent contract (docs/architecture/05-agent-sdk.md §2, §4)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, ClassVar, final
from uuid import UUID, uuid4

from .cancellation import CancellationToken
from .errors import AgentCancelledError
from .retry import RetryPolicy
from .runtime import EventPublisher, MetricsSink, NullEventPublisher, NullMetricsSink
from .types import (
    AgentReport,
    AgentRunStatus,
    AgentType,
    ExecutionResult,
    HeartbeatSignal,
    Plan,
    SelfEvaluation,
    TaskContext,
)

_FINAL_METHOD_NAMES = ("run", "cancel", "retry", "heartbeat")


class BaseAgent(ABC):
    """Every agent type subclasses this and implements exactly the four hook methods below —
    `plan`, `execute`, `evaluate`, `report`. `run`, `cancel`, `retry`, and `heartbeat` are final:
    a subclass overriding one of them fails at class-definition time (see `__init_subclass__`),
    not at first run, because the cross-cutting guarantees they provide — async scheduling,
    retries, event publishing, logging, metrics, cooperative cancellation — must not be
    skippable per agent (docs/architecture/05-agent-sdk.md §4, §1).
    """

    agent_type: ClassVar[AgentType]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for method_name in _FINAL_METHOD_NAMES:
            if getattr(cls, method_name) is not getattr(BaseAgent, method_name):
                raise TypeError(
                    f"{cls.__name__} may not override BaseAgent.{method_name}() — it is final "
                    f"by design (docs/architecture/05-agent-sdk.md §4)."
                )

    def __init__(
        self,
        *,
        agent_id: UUID,
        version: str,
        config: dict[str, Any] | None = None,
        event_publisher: EventPublisher | None = None,
        metrics_sink: MetricsSink | None = None,
        retry_policy: RetryPolicy | None = None,
        heartbeat_interval_seconds: float = 15.0,
    ) -> None:
        if not hasattr(self, "agent_type"):
            raise TypeError(f"{type(self).__name__} must set a class-level agent_type")
        self.agent_id = agent_id
        self.version = version
        self.config: dict[str, Any] = config or {}
        self.log = logging.getLogger(f"aep.agent.{self.agent_type.value}")
        self._event_publisher: EventPublisher = event_publisher or NullEventPublisher()
        self._metrics_sink: MetricsSink = metrics_sink or NullMetricsSink()
        self._retry_policy = retry_policy or RetryPolicy()
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._cancellation_token = CancellationToken()
        self._progress_percent: float | None = None
        self._progress_message: str | None = None
        self._agent_run_id: UUID | None = None
        self._task_id: UUID | None = None

    # ---- hook methods: implemented by subclasses ------------------------------------------

    @abstractmethod
    async def plan(self, context: TaskContext) -> Plan:
        """Decompose the task into an ordered set of steps."""

    @abstractmethod
    async def execute(self, plan: Plan, cancellation_token: CancellationToken) -> ExecutionResult:
        """Carry out the plan. Must poll `cancellation_token` at every safe checkpoint between
        tool calls — cancellation is cooperative, not preemptive
        (docs/architecture/05-agent-sdk.md §7)."""

    @abstractmethod
    async def evaluate(self, result: ExecutionResult) -> SelfEvaluation:
        """A cheap, immediate self-check — not the authoritative quality gate, which is the
        separate Evaluation Framework (docs/architecture/05-agent-sdk.md §14)."""

    @abstractmethod
    async def report(self, result: ExecutionResult, self_evaluation: SelfEvaluation) -> AgentReport:
        """Produce the final summary. `run()` fills in `agent_run_status`, `attempt_number`,
        `started_at`, and `completed_at` afterward — this hook doesn't need to set them."""

    # ---- lifecycle methods: final, not overridable ----------------------------------------

    @final
    def report_progress(self, *, percent: float | None = None, message: str | None = None) -> None:
        """Call from within `execute()` to update what `heartbeat()` reports next."""
        if percent is not None:
            self._progress_percent = percent
        if message is not None:
            self._progress_message = message

    @final
    def emit_metric(self, metric_name: str, value: float, **tags: Any) -> None:
        """Emit an agent-type-specific metric, additive to the standard set `run()` already
        emits automatically (docs/architecture/05-agent-sdk.md §10)."""
        self._metrics_sink.emit(metric_name, value, agent_type=self.agent_type.value, **tags)

    @final
    def heartbeat(self) -> HeartbeatSignal:
        """The current liveness/progress signal — polled by the background heartbeat loop and
        by the Orchestrator (docs/architecture/05-agent-sdk.md §8)."""
        return HeartbeatSignal(
            timestamp=datetime.now(UTC),
            progress_percent=self._progress_percent,
            message=self._progress_message,
        )

    @final
    async def cancel(self) -> None:
        """Request cooperative cancellation. Does not forcibly stop `execute()` — the running
        agent must observe its `CancellationToken` (docs/architecture/05-agent-sdk.md §7)."""
        self._cancellation_token.cancel()

    @final
    async def retry(self, context: TaskContext, *, agent_run_id: UUID | None = None) -> AgentReport:
        """Manually re-run a task from scratch — e.g. an operator-triggered retry of a run that
        already exhausted its automatic attempts. A single `run()` call's own transient-error
        retries are handled internally by `run()` and don't need this method."""
        return await self.run(context, agent_run_id=agent_run_id)

    @final
    async def run(self, context: TaskContext, *, agent_run_id: UUID | None = None) -> AgentReport:
        """The entry point the Orchestrator calls. Drives
        plan -> execute -> evaluate -> report, publishing events, logging, emitting metrics,
        and retrying transient failures around every step
        (docs/architecture/05-agent-sdk.md §4)."""
        self._agent_run_id = agent_run_id or uuid4()
        self._task_id = context.task_id
        self._cancellation_token = CancellationToken()
        await self._publish("agent_run.queued", {"attempt_number": 1})

        attempt = 1
        while True:
            started_at = datetime.now(UTC)
            heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            try:
                self._cancellation_token.raise_if_cancelled()
                self._progress_percent = None
                self._progress_message = None
                report = await self._run_attempt(context, attempt, started_at)
                return report
            except AgentCancelledError:
                report = self._finalize_report(
                    AgentRunStatus.CANCELLED, attempt, started_at, error="cancelled"
                )
                self.log.info(
                    "agent_run cancelled: agent_run_id=%s attempt=%s", self._agent_run_id, attempt
                )
                await self._publish("agent_run.cancelled", {"attempt_number": attempt})
                self._emit_standard_metrics(report)
                return report
            except Exception as exc:  # noqa: BLE001 - this is the run() boundary itself; its
                # entire job is to classify and report on whatever a hook raised, per the
                # exception-handling standard (docs/architecture/09-engineering-standards.md §6).
                retryable = self._retry_policy.is_retryable(exc)
                if retryable and attempt < self._retry_policy.max_attempts:
                    backoff = self._retry_policy.backoff_seconds(attempt)
                    self.log.warning(
                        "agent_run retrying: agent_run_id=%s attempt=%s error=%s backoff=%.1fs",
                        self._agent_run_id,
                        attempt,
                        exc,
                        backoff,
                    )
                    await self._publish(
                        "agent_run.retrying", {"attempt_number": attempt, "error": str(exc)}
                    )
                    attempt += 1
                    await asyncio.sleep(backoff)
                    continue
                report = self._finalize_report(
                    AgentRunStatus.FAILED, attempt, started_at, error=str(exc)
                )
                self.log.error(
                    "agent_run failed: agent_run_id=%s attempt=%s error=%s",
                    self._agent_run_id,
                    attempt,
                    exc,
                )
                await self._publish(
                    "agent_run.failed", {"attempt_number": attempt, "error": str(exc)}
                )
                self._emit_standard_metrics(report)
                return report
            finally:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task

    # ---- internal helpers -------------------------------------------------------------------

    async def _run_attempt(
        self, context: TaskContext, attempt: int, started_at: datetime
    ) -> AgentReport:
        await self._publish("agent_run.planning", {"attempt_number": attempt})
        self.log.info(
            "agent_run planning: agent_run_id=%s attempt=%s", self._agent_run_id, attempt
        )
        plan = await self.plan(context)
        self._cancellation_token.raise_if_cancelled()

        await self._publish("agent_run.executing", {"attempt_number": attempt})
        self.log.info(
            "agent_run executing: agent_run_id=%s attempt=%s", self._agent_run_id, attempt
        )
        result = await self.execute(plan, self._cancellation_token)
        self._cancellation_token.raise_if_cancelled()

        await self._publish("agent_run.self_evaluating", {"attempt_number": attempt})
        self_evaluation = await self.evaluate(result)
        self._cancellation_token.raise_if_cancelled()

        await self._publish("agent_run.reporting", {"attempt_number": attempt})
        report = await self.report(result, self_evaluation)
        report = report.model_copy(
            update={
                "agent_run_status": AgentRunStatus.COMPLETED,
                "attempt_number": attempt,
                "started_at": started_at,
                "completed_at": datetime.now(UTC),
            }
        )
        self.log.info(
            "agent_run completed: agent_run_id=%s attempt=%s", self._agent_run_id, attempt
        )
        await self._publish("agent_run.completed", {"attempt_number": attempt})
        self._emit_standard_metrics(report)
        return report

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_seconds)
            signal = self.heartbeat()
            await self._publish("agent_run.heartbeat", signal.model_dump(mode="json"))

    async def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope: dict[str, Any] = {
            "agent_run_id": str(self._agent_run_id),
            "task_id": str(self._task_id) if self._task_id else None,
            "agent_id": str(self.agent_id),
            "agent_type": self.agent_type.value,
            **payload,
        }
        await self._event_publisher.publish(event_type, envelope)

    def _finalize_report(
        self,
        status: AgentRunStatus,
        attempt_number: int,
        started_at: datetime,
        *,
        error: str | None = None,
    ) -> AgentReport:
        return AgentReport(
            agent_run_status=status,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            attempt_number=attempt_number,
            error=error,
        )

    def _emit_standard_metrics(self, report: AgentReport) -> None:
        tags = {"agent_type": self.agent_type.value}
        duration_ms = report.duration_ms
        if duration_ms is not None:
            self._metrics_sink.emit("agent_run.duration_ms", duration_ms, **tags)
        if report.execution_result is not None:
            self._metrics_sink.emit(
                "agent_run.input_tokens", float(report.execution_result.input_tokens), **tags
            )
            self._metrics_sink.emit(
                "agent_run.output_tokens", float(report.execution_result.output_tokens), **tags
            )
            self._metrics_sink.emit(
                "agent_run.cost_usd", report.execution_result.cost_usd, **tags
            )
        self._metrics_sink.emit("agent_run.attempt_number", float(report.attempt_number), **tags)
        if report.self_evaluation is not None:
            self._metrics_sink.emit(
                "agent_run.self_eval_passed",
                1.0 if report.self_evaluation.passed else 0.0,
                **tags,
            )
