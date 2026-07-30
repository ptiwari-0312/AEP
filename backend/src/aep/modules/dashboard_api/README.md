# dashboard_api — Dashboard API

Composes the other modules into the read/write surface the React frontend uses; owns no domain
logic of its own. See `docs/architecture/04-api-design.md` §11 and
`docs/architecture/08-dashboard-ux.md`.

## Status

Implemented: ninth full vertical slice, and the first with no database table of its own.

- `domain/` — read-model DTOs (`DashboardOverview`, `TaskGraph`, `RunningAgentSummary`, and their
  nested summary types) and domain exceptions. No persisted entities — "composes the above; owns
  no domain data itself" per the API design doc's own framing.
- `repository/` — deliberately empty. See its own docstring: this module never touches another
  module's `repository/`, and has none of its own to expose.
- `services/` — `DashboardService`: the composition logic behind all three endpoints.
- `api/` — all 3 endpoints from docs/architecture/04-api-design.md §11, wired into
  `aep.main:create_app()`.

## Composes five other modules — more collaborators than any module so far

`DashboardService` depends on `projects` (`ProjectService`/`FeatureService`), `task_memory`
(`TaskService`), `orchestrator` (`AgentRunService`/`AgentService`), `evaluation`
(`EvaluationService`), and `auth` (`AuditService`) — every dependency obtained through that
module's own `api/dependencies.py` provider function, never a `repository/` import, same rule
every other module follows. This is the expected shape of a module whose entire job is
composition, not a violation of the "keep dependencies narrow" instinct every other module
followed for its own, much smaller, purpose.

## Three small extensions to *other* modules, made while building this one

Every existing listing method on `task_memory`/`orchestrator`/`evaluation`'s services is scoped
to one parent — a feature, a task, an agent run. This module's overview/running-agents
read-models need the opposite: *global* counts and listings across every parent, for the whole
system. Rather than reconstruct that logic here by importing those modules' `repository/`
directly (which the "call the other module's `services/`, never its `repository/`" rule exists to
prevent), three small, narrowly-scoped methods were added to the modules that actually own the
data:

- `task_memory.TaskRepository.count_by_status()` / `TaskService.count_tasks_by_status()` — global
  task count by status, for `pending_approvals`.
- `orchestrator.AgentRunRepository.count_by_statuses()`/`list_by_statuses()` and the matching
  `AgentRunService` passthroughs — global agent-run count/listing by status, for `running_agents`
  and `GET /dashboard/running-agents`.
- `evaluation.EvaluationRepository.list_recent()` / `EvaluationService.list_recent_evaluations()`
  — global, newest-first evaluation listing, for `recent_evaluations`.

Each is documented in its own module's docstring/README as "added while building `dashboard_api`,"
the same pattern as every prior cross-module extension in this codebase (`task_memory.
assign_agent()`, `context_builder.assemble_content()`, `orchestrator.get_latest_run_for_task()`).

## `GET /dashboard/projects/{projectId}/task-graph`

Needs no new capability on any other module — it's assembled entirely from existing calls:
`FeatureService.list_features_for_project()` (which already 404s on a missing project, so this
module's own `ProjectNotFoundError` translation is free), then `TaskService.list_tasks_for_feature()`
per feature (looped across every cursor page, since "the full graph" means every task, not just
the first page) and `TaskService.list_dependencies()` per task for the edges.

## `GET /dashboard/running-agents`: "projects the caller can see"

The API design doc's own wording implies per-caller project visibility, but no access-control or
project-visibility concept exists anywhere in this codebase yet — role enforcement is a
documented gap in every module built so far. This reference implementation returns every
running/retrying run system-wide, the same "no role enforcement yet" stance every other module
already takes, not a new gap specific to this one.

## Known gaps, deliberate

- **`GET /dashboard/overview` has no caching layer.** The API design doc explicitly allows this
  response to be "a few seconds stale (cached, short TTL)"; this reference implementation
  computes it fresh on every request instead, which satisfies that allowance trivially but
  doesn't exploit it — a real deployment would want the cache the doc anticipates, especially
  given `list_running_agents()`'s N+1 lookups per running run (task, feature, project, agent).
- **No per-project visibility/access control** — see above.
- **No role enforcement yet** — same as every other module.
- **No Alembic migration** — not applicable; this module has no table.

## Tests

- `tests/unit/modules/dashboard_api/{domain,services}/` — SQLite-backed, no network.
  `services/test_dashboard_service.py` builds the full real cross-module graph (real `projects`/
  `task_memory`/`context_builder`/`orchestrator`/`evaluation`/`auth` services, a real `EchoAgent`
  run) to prove the overview counts, task graph, and running-agents enrichment against actual
  data, not fixtures standing in for it.
- `tests/unit/modules/{task_memory,orchestrator,evaluation}/repository/` — new test cases added
  to the *existing* repository test files for the three small extensions above, rather than new
  files, since they test methods on those modules' own repositories.
- `tests/integration/test_dashboard_api.py` — full HTTP lifecycle: a real project/task/run/
  evaluation/audit-event pipeline, then all three dashboard endpoints read through real HTTP
  requests, plus the task-graph 404 case.
