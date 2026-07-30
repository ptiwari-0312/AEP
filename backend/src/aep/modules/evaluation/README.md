# evaluation — Evaluation Framework (host side)

Runs the pluggable quality gate (DeepEval, Promptfoo, LLM-judge, unit tests, static analysis,
security scans, etc.) against agent output before it's eligible for human approval. Evaluator
plugins themselves live behind `sdk/aep-eval-sdk`. See `docs/architecture/07-evaluation-framework.md`
and `docs/architecture/04-api-design.md` §7.

## Status

Implemented: sixth full vertical slice.

- `domain/` — `Evaluation`/`EvaluationResult`/`QualityGateResult` (a local projection, not a
  re-export — see its docstring), domain exceptions. Imports `EvaluatorType`/`EvaluationStatus`
  from `aep_eval_sdk` rather than redefining them, since they're the SDK's own contract.
- `repository/` — SQLAlchemy models for `evaluations`/`evaluation_results`
  (docs/architecture/03-db-design.md §14-15), with a real FK between them (both owned by this
  module) and the usual deferred FK for `agent_run_id` (owned by `orchestrator`).
- `services/` — `EvaluationService` (trigger/list/get evaluations, the quality-gate aggregator),
  `EvaluatorRegistry` (a `{EvaluatorType: factory}` map, same scope as `orchestrator`'s
  `AgentRegistry`), and three real `BaseEvaluator` implementations: `PerformanceEvaluator`
  (self-contained — scores an agent run's own recorded cost/duration), `EchoJudgeEvaluator` (a
  dependency-free stand-in for `llm_judge`), and `UnitTestEvaluator` (a genuine pytest subprocess
  + JUnit XML parser).
- `api/` — all 5 endpoints from docs/architecture/04-api-design.md §7, wired into
  `aep.main:create_app()`.

## Cross-module boundary: calling into the Agent Orchestrator

This module talks to exactly one other module's public `services/`: `orchestrator`'s
`AgentRunService` — to confirm a run exists and has `succeeded` before evaluating it, to read its
recorded token/cost/duration figures for `PerformanceEvaluator`, and (for the quality-gate
endpoint) to find a task's latest run. It never imports `orchestrator.repository`, and it never
talks to `task_memory` directly at all — `AgentRunService.get_latest_run_for_task()` already does
the task-existence check internally, so this module only needs to translate *its* exception
(`orchestrator.domain.errors.TaskNotFoundError`), not `task_memory`'s.

## Scope: which evaluator types are actually real

Only `unit_test`, `performance`, and `llm_judge` have working implementations in this reference
backend, out of the twelve `evaluator_type`s the DB schema allows. Requesting any other type
raises `EvaluatorTypeNotRegisteredError`, translated to a 422 — the same status code the API
design doc already specifies for "unknown evaluator_type."

| Evaluator | Real? | Registered by default? |
|---|---|---|
| `performance` | Yes — reads the triggering agent run's own `input_tokens`/`output_tokens`/`cost_usd`/duration and scores them against configured thresholds. No subprocess, no LLM call. | Yes |
| `llm_judge` | `EchoJudgeEvaluator` is a real, working `BaseEvaluator` — it just reports a config-driven verdict instead of calling a real LLM (same rationale as `orchestrator`'s `EchoAgent`). Exists specifically to give the deterministic/LLM-assisted two-wave scheduling (ADR-EV2) a real second-wave evaluator to run. | Yes |
| `unit_test` | `UnitTestEvaluator` is real too — genuine `pytest` subprocess, genuine JUnit XML parsing, the same approach `examples/custom-evaluator`'s reference plugin already proved (reimplemented here since `backend/` can't depend on `examples/`). Requires a real `working_directory` in its config — deliberately has **no default**, since silently defaulting to e.g. the backend process's own cwd would risk running an unrelated test suite, not just being unconfigured. | **No** — see below. |
| The other 9 (`deepeval`, `promptfoo`, `braintrust`, `langfuse`, `integration_test`, `security_scan`, `static_analysis`, `coverage`, `architecture_rules`) | Not implemented. | No |

**Why `unit_test` isn't in the default registry:** its `working_directory` would need to come
from somewhere on a real, live `agent_run` — e.g. a checked-out repo path, or the agent's
produced diff. Neither exists: `agent_runs` (docs/architecture/03-db-design.md §9) has no column
for a code artifact or repo path, and `ExecutionResult.artifacts` (aep_agent_sdk) is never
persisted anywhere by `orchestrator`. Construct `UnitTestEvaluator` directly with an explicit
`working_directory` (this module's own tests do exactly that, against a real temp directory) once
that upstream gap is closed.

## Scheduling: real waves, policy not exposed over HTTP

`EvaluationService.trigger_evaluations()` really does split requested evaluator types into
deterministic and LLM-assisted waves via `aep_eval_sdk.category_of()`, running each wave
concurrently with `asyncio.gather` (docs/architecture/07-evaluation-framework.md §4, ADR-EV2) —
not a simplification, this is real, tested scheduling logic. What's *not* built is a per-project
`EvaluationPolicy` store: the design doc says required-vs-informational and `fail_fast`-vs-
`run_all` are "project-level configuration" without saying where that configuration lives, and no
such table exists in the DB design. Consequences:

- Every requested evaluator is treated as required — there's no way to mark one merely
  informational, so `GET /tasks/{taskId}/quality-gate`'s aggregation (§7's formula) runs against
  the full requested set every time.
- `fail_fast` (skip wave 2 if a required wave-1 evaluator failed) is a real, tested parameter on
  `EvaluationService.trigger_evaluations()`, but `POST /agent-runs/{runId}/evaluations`'s request
  body only carries `evaluator_types` per the documented contract — there's no field to select it
  over HTTP yet.

## Known gaps, deliberate

- **No async external-platform support** (Braintrust/Langfuse's `pending_external` +
  webhook/polling flow, docs/architecture/07-evaluation-framework.md §5) — no evaluator
  registered here ever returns `PENDING_EXTERNAL`, and the design doc itself doesn't define the
  webhook schema ("Out of Scope Here," §10).
- **No sandboxed tool execution** — `UnitTestEvaluator` runs `pytest` directly in whatever
  process hosts it, not inside the Agent SDK's tool-execution sandbox §6 calls for. Same
  reference-implementation stance as the reference plugin it's based on.
- **No per-project `EvaluationPolicy` store** — see above.
- **No role enforcement yet** — same as every other module.
- **No FK from `evaluations.agent_run_id`** to `agent_runs` — same cross-module `create_all()`
  ripple reason as every other module's deferred FKs. `evaluation_results.evaluation_id →
  evaluations.id` *is* a real FK, since both are owned by this module.
- **No Alembic migration yet** — same as every other module.

## Follow-through on `orchestrator`

`orchestrator.repository.agent_run_repository.AgentRunRepository` gained `get_latest_for_task()`,
and `AgentRunService` gained `get_latest_run_for_task()` — needed by the quality-gate endpoint and
not previously exposed (`list_runs_for_task()`'s ascending cursor order isn't a convenient way to
get "the latest one"). See that module's README/docstrings.

## Follow-through on this module, from `dashboard_api`

`EvaluationRepository` gained `list_recent()`, and `EvaluationService` gained
`list_recent_evaluations()` — a global, newest-first listing across every agent run, needed by
`dashboard_api`'s overview read-model (`list_for_agent_run()` is scoped to one run, which doesn't
help "recent evaluations system-wide").

## Tests

- `tests/unit/modules/evaluation/{domain,repository,services}/` — SQLite-backed, no network.
  `services/test_reference_evaluators.py` runs real `pytest` subprocesses against real temporary
  directories (`UnitTestEvaluator`) alongside the fully self-contained `PerformanceEvaluator`/
  `EchoJudgeEvaluator` tests. `services/test_evaluation_service.py` runs the full pipeline against
  a real, fully-succeeded `orchestrator` run (itself backed by real `task_memory`/`projects`/
  `context_builder` services).
- `tests/integration/test_evaluation_api.py` — full HTTP lifecycle: trigger → list → get → results
  → quality-gate, waiting for the triggering run to settle by reading `orchestrator`'s real SSE
  stream to its terminal event, plus the 404/422 cases.
