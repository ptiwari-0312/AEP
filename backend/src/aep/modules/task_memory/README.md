# task_memory — Task Memory Service

Owns the Task Graph (tasks, dependencies, state, history) derived from a Feature — the system of
record for what has and hasn't been done. See `docs/architecture/04-api-design.md` §3.

## Status

Implemented: second full vertical slice (domain → repository → services → api), wired into
`aep.main:create_app()`.

- `domain/` — `Task`/`TaskDependency`/`ExecutionHistoryEntry`, the task status state machine,
  domain exceptions.
- `repository/` — SQLAlchemy models for `tasks`/`task_dependencies`/`execution_history`
  (docs/architecture/03-db-design.md §6-7, §19), with keyset (cursor) pagination — the
  high-volume/append-only category the API design doc specifies cursor pagination for, unlike
  Project Service's offset pagination.
- `services/` — `TaskService`: the status state machine, the dependency-satisfaction gate
  (only `RUNNING` hard-requires a `blocks` dependency to be `merged` — matching the API design
  doc's own example precisely, not `READY` too), cycle detection for the dependency graph, and
  execution-history recording on every transition.
- `api/` — all endpoints from docs/architecture/04-api-design.md §3 **except**
  `task-graph:generate`, deliberately: it requires the Agent Orchestrator + a PlannerAgent,
  neither of which exist in `backend/` yet. A stub returning `202` would mislead a caller
  polling a `job_id` that never resolves — omitting it is the honest choice.

## Cross-module boundary: calling into Project Service

Creating/listing tasks requires confirming the parent Feature exists — but `features` is owned
by `modules/projects`. `TaskService` takes a `ProjectsFeatureService` (the Project Service
module's own public `services/` class) as a collaborator, obtained in `api/dependencies.py` via
`modules.projects.api.dependencies.get_feature_service` — this module's `api/` layer never
imports `modules.projects.repository`, even for wiring. The one deliberate exception:
`aep.modules.projects.domain.errors.FeatureNotFoundError` is caught and translated into this
module's own `FeatureNotFoundError`, since that exception type is part of
`FeatureService.get_feature()`'s public contract, not an internal implementation detail.

## Known gaps, deliberate

- **Real authentication is wired in now** (`aep.core.security.get_current_user_id`) — the
  previous placeholder is gone.
- **No FK from `feature_id`/`assigned_agent_id`/`changed_by_agent_id` to their owning tables** —
  `features` (projects module) and `agents` (Agent Orchestrator module) don't have real FKs for
  the same cross-module test-fixture-import reason as `changed_by_user_id` below.
  `changed_by_user_id` could now reference the `auth` module's real `users` table, but doesn't
  yet — see `modules/projects/README.md`'s identical note on why that's deferred to a real
  Alembic migration rather than done as a mechanical ripple now.
- **No role enforcement yet** on this module's endpoints either — see
  `modules/auth/README.md`'s follow-up note, which covers both modules.
- **`task-graph:generate` is not implemented** (see above).

## A real bug found and fixed while building this

SQLite's `CURRENT_TIMESTAMP` (what `server_default=func.now()` used) stores timestamps without
microseconds, but SQLAlchemy's `DateTime` bind processor always formats a Python-supplied
datetime *with* microseconds. On SQLite's TEXT-affinity storage that's a silent string mismatch:
`created_at == <python datetime>` never matched, which broke the cursor-pagination equality
branch on every tie — and ties were common, since whole-second resolution meant same-second
inserts collided constantly. Fixed by switching `created_at`/`updated_at` to a Python-side
`default=`/`onupdate=` callable instead of `server_default=func.now()`, so both the stored value
and any later comparison go through the same formatting path. Caught by an actual failing test,
not by inspection.

## Tests

- `tests/unit/modules/task_memory/{domain,repository,services}/` — SQLite-backed, no network.
- `tests/integration/test_task_memory_api.py` — full HTTP lifecycle including the
  dependency-cycle rejection, the unmet-dependency 409 on `running`, and cursor pagination.
