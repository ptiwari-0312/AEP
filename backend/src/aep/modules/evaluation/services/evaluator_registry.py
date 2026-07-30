"""Maps a requested `evaluator_type` to a live `BaseEvaluator` instance to run
(docs/architecture/07-evaluation-framework.md §8's plugin architecture).

The design doc's "backend/plugins" concept — a formal, dynamically-discovered plugin registry
(entry_points/importlib.metadata-style loading, matching the repo design doc's own
`backend/plugins/` directory) — isn't built here; this is a plain injectable `{EvaluatorType:
factory}` map, the same scope decision `orchestrator.services.agent_registry.AgentRegistry`
made for `BaseAgent` plugins. A real deployment wanting dynamic plugin discovery would replace
this class's `_default_factories()`, not its public interface.

Only two of the twelve evaluator types have a real, working implementation registered by
default: `performance` (self-contained — scores an agent run's own recorded cost/duration, no
external dependency) and `llm_judge` (a dependency-free stand-in, `EchoJudgeEvaluator` — see its
own docstring). `unit_test` has a real, working implementation too
(`reference_evaluators.UnitTestEvaluator`, genuine pytest subprocess + JUnit XML parsing) but
isn't part of the *default* registry, since it requires a real `working_directory` this
reference backend has no way to supply from a live `agent_run` yet (no artifact-persistence
mechanism exists upstream — see this module's README). The other nine types (deepeval, promptfoo,
braintrust, langfuse, integration_test, security_scan, static_analysis, coverage,
architecture_rules) have no registered implementation at all — requesting one raises
`EvaluatorTypeNotRegisteredError`, translated to a 422 by `api/router.py`, the same status the
API design doc already specifies for "unknown evaluator_type."
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aep_eval_sdk import BaseEvaluator, EvaluatorType

from .reference_evaluators import EchoJudgeEvaluator, PerformanceEvaluator

EvaluatorFactory = Callable[..., BaseEvaluator]


class EvaluatorRegistry:
    def __init__(self, factories: dict[EvaluatorType, EvaluatorFactory] | None = None) -> None:
        self._factories = factories if factories is not None else self._default_factories()

    @staticmethod
    def _default_factories() -> dict[EvaluatorType, EvaluatorFactory]:
        return {
            EvaluatorType.PERFORMANCE: lambda **kwargs: PerformanceEvaluator(**kwargs),
            EvaluatorType.LLM_JUDGE: lambda **kwargs: EchoJudgeEvaluator(**kwargs),
        }

    def is_registered(self, evaluator_type: EvaluatorType) -> bool:
        return evaluator_type in self._factories

    def create(
        self, evaluator_type: EvaluatorType, *, config: dict[str, Any] | None = None
    ) -> BaseEvaluator:
        factory = self._factories[evaluator_type]
        return factory(config=config)
