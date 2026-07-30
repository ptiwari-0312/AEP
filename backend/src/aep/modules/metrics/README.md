# metrics — Metrics Service

Aggregates cost, latency, token usage, and quality trends across agents, providers, and teams.
See `docs/architecture/04-api-design.md` §9.

## Status

Implemented: eighth full vertical slice.

- `domain/` — `Metric`/`MetricSummary`/`ProjectMetricsSummary`, domain exceptions.
- `repository/` — SQLAlchemy model for `metrics` (docs/architecture/03-db-design.md §18),
  cursor-paginated for the raw query endpoint, plus three grouped-value-listing methods that
  return raw values per bucket rather than a pre-aggregated SQL sum/avg (see below).
- `services/` — `MetricsService`: `record_metric()` (the one write path — see below),
  `list_metrics()`, `get_summary()` (grouped aggregation), `get_project_summary()` (per-project
  rollup).
- `api/` — all 3 endpoints from docs/architecture/04-api-design.md §9, wired into
  `aep.main:create_app()`.

## Read-only public surface, one internal write path

Per the API design doc's own framing — "Owns `metrics`; read-only surface (writes happen
internally as agents/evaluations complete)" — there is no `POST /metrics` endpoint anywhere in
this module's `api/`. `MetricsService.record_metric()` is this module's public `services/`
surface for *other* modules to call into, the same pattern as `auth.AuditService.record_event()`.

**No other module calls it yet.** Wiring `orchestrator`'s run-completion path or `evaluation`'s
evaluation-completion path to actually record cost/latency/quality metrics here is a real
follow-up, not attempted in this pass as a retrofit across two already-shipped modules — this
module's own tests write through `record_metric()` directly to prove the read side end-to-end,
but the rest of this codebase's real traffic doesn't feed this table yet.

## Cross-module boundary: calling into Project Service

`GET /projects/{projectId}/metrics/summary` confirms the project exists via `projects`'
`ProjectService.get_project()` (obtained through that module's own `api/dependencies.py`, never
its `repository/` directly) before rolling up — 404 on a project that doesn't exist, rather than
silently returning an empty summary.

## Two scope decisions, both explained in `services/metrics_service.py`'s own docstring

- **`group_by=provider` is not supported.** The API design doc's `group_by` enum lists
  `project|agent|provider|day`, but `metrics.entity_type`/`entity_id` is a single polymorphic
  reference per row (DB design §18) — there's no table of "providers" with their own UUIDs for
  `entity_id` to point at, unlike `project`/`agent` which map onto real rows elsewhere in the
  schema. Requesting it raises a domain error translated to 422 — the same status code the API
  design doc already specifies for "group_by/agg not in the allowed set," just with a clearer
  message than a bare schema-literal mismatch.
- **`p95` is computed in Python, not pushed down to SQL.** SQLite (this project's test backend)
  has no percentile function; Postgres (production) has `percentile_cont`, but relying on it
  would mean `sum`/`avg` and `p95` take genuinely different code paths for "the same kind of
  number." Every aggregation fetches raw values per bucket and reduces them in Python — correct,
  but exactly the kind of full-table-scan-per-query the DB design doc's own "Operational note"
  (§18) flags `metrics` as eventually needing partitioning to avoid. Percentile uses the
  nearest-rank method (not the only valid definition — linear interpolation is common too), a
  concrete choice for an otherwise-unspecified detail.

## Known gaps, deliberate

- **No metrics actually get recorded by the rest of this codebase yet** — see above.
- **No role enforcement yet** — same as every other module.
- **No FK from `metrics.entity_id`** to whatever table it polymorphically references — same
  stance as `audit_events`' identical column pair; polymorphic by design, not a deferred-FK
  oversight.
- **No Alembic migration yet** — same as every other module.

## Tests

- `tests/unit/modules/metrics/{domain,repository,services}/` — SQLite-backed, no network.
  `services/test_metrics_service.py` includes a real `ProjectService` (real project rows, not
  mocked) for the project-scoped rollup, and a `p95` test over 20 real recorded values to confirm
  the nearest-rank arithmetic, not just that a percentile function ran.
- `tests/integration/test_metrics_api.py` — full HTTP lifecycle: query raw metrics (422 without
  `metric_name`), grouped summary, the `provider` 422, and the per-project rollup, seeding rows
  by calling `MetricsService.record_metric()` directly against the test database (no HTTP
  endpoint exists to call for that — see above).
