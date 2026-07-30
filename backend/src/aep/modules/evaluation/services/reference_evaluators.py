"""Real, working `BaseEvaluator` implementations registered by this module's default
`EvaluatorRegistry`, plus a real subprocess-based one (`UnitTestEvaluator`) that isn't part of
that default. See `evaluator_registry.py`'s module docstring for which is which and why.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from aep_eval_sdk import (
    AgentRunContext,
    BaseEvaluator,
    EvaluationReport,
    EvaluationStatus,
    EvaluatorInput,
    EvaluatorOutput,
    EvaluatorType,
    MetricScore,
)
from pydantic import BaseModel, Field


class PerformanceEvaluatorConfig(BaseModel):
    """A `None` threshold means that metric always passes — no limit configured, not a silent
    0 (which would fail every run)."""

    max_cost_usd: float | None = None
    max_duration_seconds: float | None = None


class PerformanceEvaluator(BaseEvaluator):
    """Scores an agent run's own recorded cost/duration against configured thresholds — real,
    deterministic, and self-contained: no subprocess, no LLM call, no dependency on artifacts
    this system doesn't persist anywhere (see this module's README's "Known gaps" for why a
    real `unit_test`-style evaluator can't default to something similarly self-contained).
    `EvaluationRunnerService` populates `AgentRunContext.metadata` with the triggering
    `agent_run`'s own `input_tokens`/`output_tokens`/`cost_usd`/`duration_seconds` — this
    evaluator only reads them back, it doesn't compute them itself.
    """

    evaluator_type = EvaluatorType.PERFORMANCE

    def __init__(self, *, config: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(config=config, **kwargs)
        self._settings = PerformanceEvaluatorConfig.model_validate(self.config)

    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        return EvaluatorInput(
            agent_run_id=agent_run.agent_run_id,
            task_id=agent_run.task_id,
            fixtures=dict(agent_run.metadata),
        )

    async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
        return EvaluatorOutput(raw_result=dict(evaluator_input.fixtures))

    async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
        cost_usd = output.raw_result.get("cost_usd")
        duration_seconds = output.raw_result.get("duration_seconds")

        scores: list[MetricScore] = []
        if self._settings.max_cost_usd is not None and cost_usd is not None:
            scores.append(
                MetricScore(
                    metric_name="cost_usd",
                    score=cost_usd,
                    threshold=self._settings.max_cost_usd,
                    passed=cost_usd <= self._settings.max_cost_usd,
                )
            )
        if self._settings.max_duration_seconds is not None and duration_seconds is not None:
            scores.append(
                MetricScore(
                    metric_name="duration_seconds",
                    score=duration_seconds,
                    threshold=self._settings.max_duration_seconds,
                    passed=duration_seconds <= self._settings.max_duration_seconds,
                )
            )
        if not scores:
            # No thresholds configured and/or no metadata available — nothing to fail on.
            scores.append(MetricScore(metric_name="no_thresholds_configured", score=1.0, passed=True))
        return scores

    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        return EvaluationReport(
            status=EvaluationStatus.PASSED if all(s.passed for s in scores) else EvaluationStatus.FAILED,
            scores=scores,
        )


class EchoJudgeEvaluatorConfig(BaseModel):
    passed: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EchoJudgeEvaluator(BaseEvaluator):
    """A dependency-free stand-in for a real LLM-judge integration — same rationale as
    `orchestrator.services.reference_agent.EchoAgent` standing in for a real LLM-backed coding
    agent: no Model Provider credentials are wired into `backend/`, so this evaluator reports a
    config-driven verdict instead of calling one. Registered as `EvaluatorType.LLM_JUDGE`
    specifically so `EvaluationRunnerService`'s deterministic-then-LLM-assisted wave scheduling
    (docs/architecture/07-evaluation-framework.md §4, ADR-EV2) has a real second-wave evaluator
    to schedule and test against.
    """

    evaluator_type = EvaluatorType.LLM_JUDGE

    def __init__(self, *, config: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(config=config, **kwargs)
        self._settings = EchoJudgeEvaluatorConfig.model_validate(self.config)

    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        return EvaluatorInput(agent_run_id=agent_run.agent_run_id, task_id=agent_run.task_id)

    async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
        return EvaluatorOutput(raw_result={"passed": self._settings.passed})

    async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
        passed = bool(output.raw_result["passed"])
        return [
            MetricScore(
                metric_name="judge_verdict",
                score=self._settings.confidence if passed else 1.0 - self._settings.confidence,
                threshold=0.5,
                passed=passed,
            )
        ]

    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        return EvaluationReport(
            status=EvaluationStatus.PASSED if scores[0].passed else EvaluationStatus.FAILED,
            scores=scores,
        )


class UnitTestEvaluatorConfig(BaseModel):
    """`working_directory` has no default — see this module's README for why silently defaulting
    it (e.g. to the backend process's own cwd) would be actively harmful rather than merely
    unconfigured."""

    working_directory: str
    test_path: str = "."
    min_pass_rate: float = Field(default=1.0, ge=0.0, le=1.0)
    timeout_seconds: float = 60.0
    pytest_args: list[str] = Field(default_factory=list)


class UnitTestEvaluator(BaseEvaluator):
    """Runs real pytest, as a real subprocess, against a real directory, and parses its real
    JUnit XML report — the same approach `examples/custom-evaluator`'s reference plugin already
    proved end-to-end; reimplemented here (not imported from `examples/`, which isn't a
    `backend/` dependency) since this module needs one it can register directly.

    Not part of `EvaluatorRegistry`'s default set (see `evaluator_registry.py`) — construct one
    explicitly (as this module's own tests do) once a real `working_directory` is available.
    """

    evaluator_type = EvaluatorType.UNIT_TEST

    def __init__(self, *, config: dict[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(config=config, **kwargs)
        self._settings = UnitTestEvaluatorConfig.model_validate(self.config)

    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        return EvaluatorInput(
            agent_run_id=agent_run.agent_run_id,
            task_id=agent_run.task_id,
            fixtures={"working_directory": self._settings.working_directory},
        )

    async def execute(self, evaluator_input: EvaluatorInput) -> EvaluatorOutput:
        working_directory = Path(evaluator_input.fixtures["working_directory"]).resolve()
        target_path = working_directory / self._settings.test_path

        with tempfile.TemporaryDirectory() as tmp_dir:
            junit_report_path = Path(tmp_dir) / "junit-report.xml"
            command = [
                sys.executable,
                "-m",
                "pytest",
                str(target_path),
                f"--junitxml={junit_report_path}",
                f"--confcutdir={working_directory}",
                "--rootdir",
                str(working_directory),
                "-p",
                "no:cacheprovider",
                "-q",
                *self._settings.pytest_args,
            ]
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self._settings.timeout_seconds
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                raise TimeoutError(
                    f"pytest did not complete within {self._settings.timeout_seconds}s"
                ) from None

            summary = _parse_junit_report(junit_report_path)

        return EvaluatorOutput(
            raw_result=summary, logs=[stdout.decode(errors="replace"), stderr.decode(errors="replace")]
        )

    async def score(self, output: EvaluatorOutput) -> list[MetricScore]:
        raw = output.raw_result
        total = raw["total"]
        failed = raw["failed"] + raw["errors"]
        pass_rate = (total - failed) / total if total else 0.0
        return [
            MetricScore(
                metric_name="pass_rate",
                score=pass_rate,
                threshold=self._settings.min_pass_rate,
                passed=pass_rate >= self._settings.min_pass_rate,
                details={"total": total, "passed": total - failed, "failed": failed},
            ),
            MetricScore(metric_name="failures", score=float(failed), threshold=0.0, passed=failed == 0),
        ]

    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        return EvaluationReport(
            status=EvaluationStatus.PASSED if all(s.passed for s in scores) else EvaluationStatus.FAILED,
            scores=scores,
        )


def _parse_junit_report(path: Path) -> dict[str, int]:
    if not path.exists():
        raise RuntimeError(
            "pytest did not produce a junit report — check test_path/pytest_args "
            "(pytest likely errored before the test session started)"
        )
    root = ET.parse(path).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        raise RuntimeError("junit report contained no <testsuite> element")
    return {
        "total": int(suite.get("tests", 0)),
        "failed": int(suite.get("failures", 0)),
        "errors": int(suite.get("errors", 0)),
        "skipped": int(suite.get("skipped", 0)),
    }
