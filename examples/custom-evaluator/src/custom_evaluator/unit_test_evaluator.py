"""A UnitTestEvaluator: runs pytest against a target project and reports pass/fail metrics.

Reference implementation built against sdk/aep-eval-sdk, for the `unit_test` evaluator type —
a deterministic, tool-based evaluator (docs/architecture/07-evaluation-framework.md §3): no LLM
call, just a subprocess and a parsed report. The sandbox/isolation this should run inside for
real agent-produced code (docs/architecture/07-evaluation-framework.md §6) is a backend
infrastructure concern this reference plugin doesn't provide — it just runs the subprocess in
whatever environment hosts it.
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

from .config import UnitTestEvaluatorConfig


class UnitTestEvaluator(BaseEvaluator):
    evaluator_type = EvaluatorType.UNIT_TEST

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._settings = UnitTestEvaluatorConfig.model_validate(self.config)

    async def prepare(self, agent_run: AgentRunContext) -> EvaluatorInput:
        working_directory = agent_run.metadata.get("repo_path", self._settings.working_directory)
        return EvaluatorInput(
            agent_run_id=agent_run.agent_run_id,
            task_id=agent_run.task_id,
            config=self._settings.model_dump(),
            fixtures={"working_directory": working_directory},
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
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
            raw_result=summary,
            logs=[stdout.decode(errors="replace"), stderr.decode(errors="replace")],
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
            MetricScore(
                metric_name="failures",
                score=float(failed),
                threshold=0.0,
                passed=failed == 0,
            ),
        ]

    async def report(self, scores: list[MetricScore]) -> EvaluationReport:
        all_passed = all(score.passed for score in scores)
        return EvaluationReport(
            status=EvaluationStatus.PASSED if all_passed else EvaluationStatus.FAILED,
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
