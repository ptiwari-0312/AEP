# orchestrator — Agent Orchestrator

Assigns agents to tasks, drives their lifecycle (plan → execute → evaluate → report), and enforces
the human-approval gate before merge. See `docs/architecture/05-agent-sdk.md` and
`docs/architecture/04-api-design.md` §5.

## Status

Implemented: fifth full vertical slice.

- `domain/` — `Agent`/`AgentRun`/`TaskSummary` (a local projection, not a re-export, of
  `task_memory`'s `Task` — see its docstring), domain exceptions. Imports `AgentType` from
  `aep_agent_sdk` rather than redefining it, since the eight agent types are the SDK's own
  contract.
- `repository/` — SQLAlchemy models for `agents`/`agent_runs` (docs/architecture/03-db-design.md
  §8-9). The first module where a *cross-table* FK inside its own tables is real
  (`agent_runs.agent_id → agents.id`) alongside the usual deferred cross-*module* FKs
  (`task_id`, `context_package_id`).
- `services/` — `AgentService` (agents CRUD), `AgentRunService` (assign/start/list/get/cancel/
  retry/subscribe), `TaskReviewService` (approve/reject/merge), `EchoAgent` (a real, dependency-
  free reference `BaseAgent`), `AgentRegistry`, `RunRegistry` (cancellation bookkeeping),
  `RunEventBroker` (in-memory SSE pub/sub).
- `api/` — all 13 endpoints from docs/architecture/04-api-design.md §5, wired into
  `aep.main:create_app()`.

## Cross-module boundaries

Starting a run resolves through **three** other modules' public `services/` (never their
`domain/`/`repository/`): `task_memory`'s `TaskService` (confirm the task, read/set
`assigned_agent_id`, drive its status transitions — including reusing its own
dependency-satisfaction gate for free, since `RUNNING` is dependency-gated there already),
`context_builder`'s `ContextBuilderService` (confirm the context package belongs to this task,
and call the new `assemble_content()` to get real text for `TaskContext.content`), and `auth`'s
`AuditService` (the one documented audit write, on `approve`).

**Background execution needs its own DB session.** A run executes as an in-process `asyncio`
background task (see `services/run_registry.py`'s docstring for why not a distributed queue), so
the request that started it returns before the run settles, and the background coroutine can't
reuse the request-scoped session. Rather than import `task_memory`/`projects`' `repository/` to
rebuild their services against a new session — which the "call the other module's `services/`,
never its `repository/`" rule exists to prevent — it calls those modules' own
`api/dependencies.py` provider functions directly with an explicit session: the same functions
FastAPI's `Depends()` calls, just invoked as plain Python functions since no HTTP request exists
for a background task to hang a `Depends()` chain off of. See `services/agent_run_service.py`'s
module docstring.

## A design decision: who promotes `evaluating -> awaiting_approval`?

The vision doc's pipeline is "...Generate Code -> Run Evaluations -> Human Approval -> Merge," and
the API design doc frames this module as driving task status "in concert with" Task Memory — but
the Evaluation Framework module (owner of `evaluations`/`evaluation_results`, the *authoritative*
quality gate) doesn't exist in `backend/` yet. Without it, nothing would ever move a task out of
`evaluating`. This module's `_execute_and_persist()` promotes `evaluating -> awaiting_approval`
itself, gated on the agent's own `SelfEvaluation.passed` (aep_agent_sdk's own docstring is explicit
that this is "a cheap, immediate self-check — not the authoritative quality gate"). This is a
deliberate stand-in, not a claim that self-evaluation *is* the real gate — a real Evaluation
Framework module should insert itself between these two states instead.

## A concurrency bug found and fixed while building this

`GET /agent-runs/{runId}/events`'s in-memory broker (`services/run_events.py`) was originally
pure fire-and-forget pub/sub — publish drops the event if nobody's subscribed yet, the same
semantics `core.events.RedisEventPublisher`'s own docstring documents for real Redis Pub/Sub.
That's fine for a slow agent, but `EchoAgent` with no configured delay runs its entire
`plan -> execute -> evaluate -> report` lifecycle — publishing every event, including the
terminal one — in well under a millisecond, almost always *before* a client's `GET .../events`
request has even been scheduled. A subscriber that attaches after the fact waited forever for an
event that already happened. Fixed by having the broker retain a per-run history buffer and
replay it to every new subscriber before it starts waiting live — caught by an integration test
hanging, not by inspection.

A related, narrower version of the same class of bug: `BaseAgent.run()` (aep_agent_sdk, `@final`)
publishes its own terminal event (`agent_run.completed`/`failed`/`cancelled`) as the last thing it
does *before returning* — strictly before this module's own `_execute_and_persist()` even starts
its DB write. A client that saw that event and immediately `GET /agent-runs/{runId}` could read a
row still showing `running`. Fixed by publishing an additional `agent_run.persisted` event *after*
the commit, and treating that — not the SDK's own terminal events — as what actually ends the SSE
stream (`run_events.py`'s `_TERMINAL_EVENT_TYPES`), so by the time the stream closes, the row is
guaranteed to reflect it.

## Known gaps, deliberate

- **No real LLM-backed agent.** `EchoAgent` is a genuine `BaseAgent` subclass (real inheritance,
  real cooperative cancellation, real event publishing) but calls no external API — no paid
  Anthropic/OpenAI/etc. credentials are wired into `backend/` (same stance `context_builder` takes
  for embeddings). A real deployment registers `DocumentationAgent`-style instances (see
  `examples/custom-agent`) backed by a real `ModelProvider` in `AgentRegistry` instead.
  `provider`/`model_name` on `POST .../runs` are recorded on the persisted row but don't affect
  execution — there's no Model Provider registry/enablement concept in `backend/` to validate
  them against beyond the four literal names in the request schema.
- **`evaluating -> awaiting_approval` is gated on the agent's own cheap self-evaluation, not the
  (not yet built) Evaluation Framework's authoritative gate** — see above.
- **In-process, not distributed, execution and event delivery.** `RunRegistry`/`RunEventBroker`
  are per-process singletons; cancelling or streaming a run only works against the process that's
  actually running it. A real deployment needs a distributed queue (Redis, per the architecture
  docs) and `RedisEventPublisher`'s channel instead of the in-memory broker.
- **`force_reindex`/re-embedding aren't things this module or `context_builder` do** — see
  `context_builder/README.md`.
- **No role enforcement yet** — same as every other module.
- **No FK from `agent_runs.task_id`/`context_package_id`** to their owning tables — same
  cross-module `create_all()` ripple reason as every other module's deferred FKs.
  `agent_runs.agent_id -> agents.id` *is* a real FK, since both are owned by this module.
- **No Alembic migration yet** — same as every other module.

## Follow-through on `task_memory`

`task_memory.TaskService` gained `assign_agent()` — `update_task()` never exposed a way to set
`assigned_agent_id`, since assignment is this module's HTTP contract
(`POST /tasks/{taskId}/assign`), not `task_memory`'s own. See that module's README.

## Tests

- `tests/unit/modules/orchestrator/{domain,repository,services}/` — SQLite-backed, no network.
  `services/test_reference_agent.py` exercises `EchoAgent` directly (completion, configured
  failure, cooperative cancellation). `services/test_agent_run_service.py` runs the full pipeline
  against real `task_memory`/`projects`/`context_builder` services and real local files, awaiting
  the tracked background `asyncio.Task` directly (`RunRegistry.wait_for()`) for determinism
  instead of sleeping/polling.
- `tests/integration/test_orchestrator_api.py` — full HTTP lifecycle: register → assign → start
  run → read the real SSE stream to completion → approve → merge, plus the 404/409 cases. Waits
  for a run to settle by reading `GET .../events` to its terminal event — the same mechanism a
  real client would use — rather than sleeping.
