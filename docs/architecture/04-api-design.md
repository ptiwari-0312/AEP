# AEP — REST API Design

> Produced from `prompts/promt4-APIDesign.md`. Covers every module from
> [01-vision-and-principles.md](01-vision-and-principles.md), backed by the schema in
> [03-db-design.md](03-db-design.md), served from `backend/src/aep/modules/*/api` per
> [02-repo-design.md](02-repo-design.md). Specification only — no implementation. The
> `frontend/api-client` package is generated from this spec's OpenAPI document, never hand-written.

## 0. Global Conventions

These apply to every endpoint below; they are stated once here rather than repeated per-endpoint.

### 0.1 Versioning

- URI-based: `/api/v1/...`. A breaking change ships as `/api/v2/...` alongside `v1`, never as an
  in-place change.
- Deprecated-but-still-`v1` endpoints send `Deprecation: true` and `Sunset: <date>` response
  headers for at least one release cycle before removal.
- URI versioning (not header/content-negotiation versioning) is chosen specifically because
  `frontend/api-client` and the SDK examples are generated from the OpenAPI document per version —
  a stable URI makes generated clients trivially pinnable.

### 0.2 Authentication & Authorization

- Every endpoint requires `Authorization: Bearer <JWT>` unless explicitly marked **Public**.
- The JWT is issued by the Authentication Service (§1) and carries the caller's `user_id` and
  resolved roles (from `roles`/`user_roles`, per the DB design).
- Each endpoint below states the minimum role required: `viewer` (read-only), `engineer`
  (create/modify work), `reviewer` (approve/reject), `admin` (manage agents, providers, users).
  Roles are additive — `admin` satisfies any lower requirement.
- Agent-to-backend calls (e.g. an `agent_run` reporting progress) authenticate with a
  service-scoped JWT tied to `agents.id`, not a user token — this is what lets `audit_events` and
  `execution_history` distinguish `actor_user_id` from `actor_agent_id`.

### 0.3 Pagination

Two styles, chosen per table's access pattern (matches §0 of the DB design's own conventions):

- **Offset pagination** (`?page=1&page_size=20`, default `page_size=20`, max `100`) for small,
  bounded collections: projects, features, agents, prompt templates. Response envelope:
  ```
  { "items": [...], "page": 1, "page_size": 20, "total": 137 }
  ```
- **Cursor pagination** (`?cursor=<opaque>&limit=50`, default/max `limit=100`) for
  high-volume/append-only collections: tasks (within a large feature), agent runs, evaluations,
  metrics, audit events, execution history. Response envelope:
  ```
  { "items": [...], "next_cursor": "opaque-string-or-null", "has_more": true }
  ```
  Cursor pagination is used here specifically because offset pagination over an append-only table
  that's being written to concurrently skips/duplicates rows under page drift; a cursor doesn't.

### 0.4 Filtering & Sorting

- Filters are query params named after the column: `?status=active`, `?agent_type=coding`.
- Date/number ranges use `_from`/`_to` suffixes: `?created_at_from=2026-01-01&created_at_to=2026-02-01`.
- Sorting: `?sort=field` (ascending) or `?sort=-field` (descending); multiple fields comma-separated.
  Unsupported sort fields return `400 Bad Request`, not a silent no-op.

### 0.5 Standard Status Codes

| Code | Meaning | Used for |
|---|---|---|
| 200 | OK | successful GET/PATCH |
| 201 | Created | successful POST creating a resource |
| 202 | Accepted | async operation enqueued (agent run, context generation) |
| 204 | No Content | successful DELETE / action with no body |
| 400 | Bad Request | malformed request (bad JSON, unknown sort field) |
| 401 | Unauthorized | missing/invalid/expired JWT |
| 403 | Forbidden | valid JWT, insufficient role |
| 404 | Not Found | resource doesn't exist or caller lacks visibility |
| 409 | Conflict | unique constraint violation, invalid state transition |
| 422 | Unprocessable Entity | request is well-formed JSON but fails field validation |
| 429 | Too Many Requests | rate limit exceeded |
| 500 | Internal Server Error | unhandled failure |

### 0.6 Error Response Format

All non-2xx responses use RFC 7807 Problem Details:

```json
{
  "type": "https://aep.dev/errors/validation-error",
  "title": "Validation failed",
  "status": 422,
  "detail": "One or more fields failed validation.",
  "instance": "/api/v1/projects",
  "errors": [
    { "field": "slug", "message": "must match ^[a-z0-9-]+$" }
  ]
}
```

`errors[]` is present only on `422`. Every error `type` is a stable, documented URI so client code
can branch on error category, not on `title`/`detail` string content.

### 0.7 Validation Rules (General)

- All request bodies are validated against the module's Pydantic schema server-side (per the
  strong-typing principle) — client-side validation is a UX nicety, never trusted.
- String length limits mirror the DB column limits in the DB design doc exactly (no endpoint
  accepts a value the schema can't store).
- State-transition endpoints (task status, feature status, approvals) validate the transition
  against the allowed state machine and return `409 Conflict` — with the current and attempted
  state named in `detail` — on an illegal transition, not `422`.

---

## 1. Authentication & Users API

Owned by the Authentication Service.

| Method | URI | Auth | Summary |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Public | Exchange an OAuth provider code for an AEP session |
| POST | `/api/v1/auth/refresh` | Public (refresh token) | Exchange a refresh token for a new access token |
| POST | `/api/v1/auth/logout` | any | Revoke the current refresh token |
| GET | `/api/v1/users/me` | any | Current user's profile + resolved roles |
| GET | `/api/v1/users` | admin | List users |
| GET | `/api/v1/users/{userId}` | admin | Get a user |
| PATCH | `/api/v1/users/{userId}` | admin | Update status/display_name |
| GET | `/api/v1/roles` | any | List available roles |
| POST | `/api/v1/users/{userId}/roles` | admin | Grant a role |
| DELETE | `/api/v1/users/{userId}/roles/{roleId}` | admin | Revoke a role |

#### `POST /api/v1/auth/login` (Public)
- **Request body:** `{ "provider": "github|google|okta", "code": "string" }`
- **Response `200`:** `{ "access_token": "jwt", "refresh_token": "opaque", "expires_in": 3600, "user": {UserSummary} }`
- **Status codes:** 200; 400 (missing `code`); 401 (provider rejected code)
- **Validation:** `provider` must be one of the configured providers; `code` required, non-empty.

#### `GET /api/v1/users/me`
- **Response `200`:** `{ id, email, display_name, status, roles: [string], created_at }`
- **Status codes:** 200; 401

#### `GET /api/v1/users`
- **Query params:** `status`, `email` (exact match), pagination (offset-style, §0.3), `sort`
- **Response `200`:** paginated envelope of `UserSummary`
- **Status codes:** 200; 401; 403

#### `POST /api/v1/users/{userId}/roles`
- **Request body:** `{ "role_id": "uuid" }`
- **Response `201`:** `{ user_id, role_id, granted_at, granted_by }`
- **Status codes:** 201; 404 (user or role not found); 409 (already granted); 422

---

## 2. Project Service API

Owns `projects`, `features`, `git_repositories`.

| Method | URI | Auth | Summary |
|---|---|---|---|
| POST | `/api/v1/projects` | engineer | Create a project |
| GET | `/api/v1/projects` | viewer | List projects |
| GET | `/api/v1/projects/{projectId}` | viewer | Get a project |
| PATCH | `/api/v1/projects/{projectId}` | engineer (owner) / admin | Update a project |
| POST | `/api/v1/projects/{projectId}/archive` | engineer (owner) / admin | Archive a project |
| PUT | `/api/v1/projects/{projectId}/repository` | engineer (owner) / admin | Attach/replace the linked git repository |
| POST | `/api/v1/projects/{projectId}/features` | engineer | Create a feature |
| GET | `/api/v1/projects/{projectId}/features` | viewer | List features on a project |
| GET | `/api/v1/features/{featureId}` | viewer | Get a feature |
| PATCH | `/api/v1/features/{featureId}` | engineer | Update a feature |
| POST | `/api/v1/features/{featureId}/status` | engineer / reviewer | Transition feature status |

#### `POST /api/v1/projects`
- **Request body:**

  | field | type | required | rules |
  |---|---|---|---|
  | name | string | yes | 1–255 chars |
  | slug | string | yes | 1–100 chars, `^[a-z0-9-]+$`, unique |
  | description | string | no | ≤10,000 chars |
  | git_repository_id | uuid | no | must reference an existing repo |

- **Response `201`:** full Project representation (mirrors `projects` table minus internal columns).
- **Status codes:** 201; 401; 403; 409 (`slug` taken); 422.

#### `GET /api/v1/projects`
- **Query params:** `status` (`active`\|`archived`), `owner_user_id`, `q` (name search),
  pagination (offset-style), `sort` (`name`, `created_at`).
- **Response `200`:** paginated envelope of `ProjectSummary`.
- **Status codes:** 200; 401.

#### `PATCH /api/v1/projects/{projectId}`
- **Request body:** any subset of `{ name, description }` (`slug`, `owner_user_id` are immutable
  via this endpoint — ownership transfer is a deliberately separate, audited admin action not
  specified here to keep this endpoint's blast radius small).
- **Status codes:** 200; 401; 403 (not owner/admin); 404; 422.

#### `POST /api/v1/features/{featureId}/status`
- **Request body:** `{ "to_status": "in_progress|in_review|done|cancelled", "reason": "string?" }`
- **Response `200`:** updated Feature.
- **Status codes:** 200; 404; 409 (illegal transition, e.g. `done` → `draft`); 422.
- **Validation:** transition must be a legal edge in the Feature state machine (DB design §5).

---

## 3. Task Memory Service API

Owns `tasks`, `task_dependencies`, `execution_history`.

| Method | URI | Auth | Summary |
|---|---|---|---|
| POST | `/api/v1/features/{featureId}/task-graph:generate` | engineer | Generate a task graph for a feature |
| POST | `/api/v1/features/{featureId}/tasks` | engineer | Manually create a task |
| GET | `/api/v1/features/{featureId}/tasks` | viewer | List tasks for a feature (graph view) |
| GET | `/api/v1/tasks/{taskId}` | viewer | Get a task |
| PATCH | `/api/v1/tasks/{taskId}` | engineer | Update task fields (title/description/priority) |
| POST | `/api/v1/tasks/{taskId}/status` | engineer / orchestrator | Transition task status |
| POST | `/api/v1/tasks/{taskId}/dependencies` | engineer | Add a dependency |
| DELETE | `/api/v1/tasks/{taskId}/dependencies/{dependencyId}` | engineer | Remove a dependency |
| GET | `/api/v1/tasks/{taskId}/execution-history` | viewer | Task status-change timeline |

#### `POST /api/v1/features/{featureId}/task-graph:generate`
- **Request body:** `{ "strategy": "default|conservative", "regenerate": false }`
- **Response `202`:** `{ "job_id": "uuid", "status": "queued" }` — task-graph generation is async
  (it may itself invoke a PlannerAgent); poll `GET /api/v1/features/{featureId}/tasks` or subscribe
  via the event stream (see §5.6) for completion.
- **Status codes:** 202; 404 (feature not found); 409 (`regenerate=false` and a graph already
  exists); 422.

#### `GET /api/v1/features/{featureId}/tasks`
- **Query params:** `status`, `task_type`, `assigned_agent_id`, cursor pagination, `sort`.
- **Response `200`:** cursor envelope of `TaskSummary`, each including `depends_on: [taskId]` so the
  Dashboard's Task Graph screen can render edges from one call rather than N.
- **Status codes:** 200; 404.

#### `POST /api/v1/tasks/{taskId}/status`
- **Request body:** `{ "to_status": "<see tasks.status enum>", "reason": "string?" }`
- **Response `200`:** updated Task; also appends one `execution_history` row.
- **Status codes:** 200; 404; 409 (illegal transition or unmet dependencies — e.g. moving to
  `running` while a `depends_on` task is not `merged`); 422.

#### `POST /api/v1/tasks/{taskId}/dependencies`
- **Request body:** `{ "depends_on_task_id": "uuid", "dependency_type": "blocks|informs" }`
- **Response `201`:** the dependency edge.
- **Status codes:** 201; 404; 409 (would create a cycle, or duplicate edge); 422 (self-dependency).

---

## 4. Context Builder API

Owns `context_packages`, `context_package_sources`; reads `source_documents`.

| Method | URI | Auth | Summary |
|---|---|---|---|
| POST | `/api/v1/tasks/{taskId}/context-packages` | engineer / orchestrator | Generate a context package for a task |
| GET | `/api/v1/tasks/{taskId}/context-packages` | viewer | List a task's context package history |
| GET | `/api/v1/context-packages/{contextPackageId}` | viewer | Get a context package (metadata) |
| GET | `/api/v1/context-packages/{contextPackageId}/sources` | viewer | Ranked source documents included/excluded |
| GET | `/api/v1/projects/{projectId}/source-documents` | viewer | List indexed source documents |

#### `POST /api/v1/tasks/{taskId}/context-packages`
- **Request body:** `{ "max_tokens": 100000, "force_reindex": false }`
- **Response `202`:** `{ "job_id": "uuid", "status": "queued" }` — generation involves ranking and
  possibly re-embedding documents, so it's async like task-graph generation.
- **Status codes:** 202; 404; 422 (`max_tokens` ≤ 0).

#### `GET /api/v1/context-packages/{contextPackageId}/sources`
- **Query params:** `included` (`true`\|`false`\|omit for both), offset pagination, `sort=rank`.
- **Response `200`:** paginated list of `{ source_document_id, uri, doc_type, relevance_score, rank, included, token_count }`.
- **Status codes:** 200; 404.
- This endpoint is what makes the Context Builder's "explain ranking" requirement (from its own
  design doc) inspectable via API rather than only in logs.

---

## 5. Agent Orchestrator API

Owns `agents`, `agent_runs`; drives task status transitions in concert with §3.

| Method | URI | Auth | Summary |
|---|---|---|---|
| GET | `/api/v1/agents` | viewer | List registered agents |
| GET | `/api/v1/agents/{agentId}` | viewer | Get an agent |
| POST | `/api/v1/agents` | admin | Register an agent |
| PATCH | `/api/v1/agents/{agentId}` | admin | Enable/disable, update config |
| POST | `/api/v1/tasks/{taskId}/assign` | engineer | Assign an agent to a task |
| POST | `/api/v1/tasks/{taskId}/runs` | engineer / orchestrator | Start a new agent run |
| GET | `/api/v1/tasks/{taskId}/runs` | viewer | List runs for a task |
| GET | `/api/v1/agent-runs/{runId}` | viewer | Get a run |
| POST | `/api/v1/agent-runs/{runId}/cancel` | engineer / reviewer | Cancel a running run |
| POST | `/api/v1/agent-runs/{runId}/retry` | engineer | Retry a failed run |
| GET | `/api/v1/agent-runs/{runId}/events` | viewer | Server-Sent Events stream of run progress |
| POST | `/api/v1/tasks/{taskId}/approve` | reviewer | Human-approve a task's output |
| POST | `/api/v1/tasks/{taskId}/reject` | reviewer | Reject a task's output, sends it back |
| POST | `/api/v1/tasks/{taskId}/merge` | reviewer / admin | Merge an approved task's output |

#### `POST /api/v1/tasks/{taskId}/runs`
- **Request body:** `{ "provider": "claude|openai|gemini|vertex_ai", "model_name": "string", "context_package_id": "uuid" }`
- **Response `202`:** `{ "agent_run_id": "uuid", "status": "queued" }`
- **Status codes:** 202; 404 (task/context package not found); 409 (task has no assigned agent, or
  is not in a runnable status); 422 (unknown provider/model).
- **Validation:** `provider` must be a currently-enabled provider (§8); the task must already have
  `assigned_agent_id` set (via `/assign`) — a run cannot silently pick an agent.

#### `GET /api/v1/agent-runs/{runId}/events`
- **Response:** `Content-Type: text/event-stream`; events named `status`, `heartbeat`, `log`,
  `completed`, `failed`, each a JSON payload. This is the one intentionally non-JSON-request/response
  endpoint in the spec — it exists because polling `GET /agent-runs/{runId}` at sub-second
  intervals for a long-running agent doesn't scale, and it maps directly to the Agent SDK's
  `heartbeat()`/event-publishing contract.
- **Status codes:** 200 (stream opens); 404.

#### `POST /api/v1/tasks/{taskId}/approve`
- **Request body:** `{ "comment": "string?" }`
- **Response `200`:** updated Task (`status: approved`), plus an `audit_events` row is written
  server-side (actor = calling reviewer).
- **Status codes:** 200; 403 (caller lacks `reviewer`); 404; 409 (task not in `awaiting_approval`
  — you cannot approve work that hasn't cleared the quality gate, enforced here per the vision
  doc's two-gate rule, not left to client discipline).

#### `POST /api/v1/tasks/{taskId}/merge`
- **Response `200`:** updated Task (`status: merged`).
- **Status codes:** 200; 404; 409 (task not in `approved` status).

---

## 6. Prompt Library API

Owns `prompt_templates`, `prompt_versions`.

| Method | URI | Auth | Summary |
|---|---|---|---|
| POST | `/api/v1/prompt-templates` | engineer | Create a template |
| GET | `/api/v1/prompt-templates` | viewer | List templates |
| GET | `/api/v1/prompt-templates/{templateId}` | viewer | Get a template (+ active version inline) |
| POST | `/api/v1/prompt-templates/{templateId}/versions` | engineer | Create a new version |
| GET | `/api/v1/prompt-templates/{templateId}/versions` | viewer | List versions |
| GET | `/api/v1/prompt-templates/{templateId}/versions/{versionNumber}` | viewer | Get a specific version |
| POST | `/api/v1/prompt-templates/{templateId}/versions/{versionNumber}/activate` | engineer | Make this version active |

#### `POST /api/v1/prompt-templates/{templateId}/versions`
- **Request body:** `{ "content": "string", "variables": [{"name": "string", "required": true}], "activate": false }`
- **Response `201`:** the new `PromptVersion` (`version_number` auto-incremented server-side).
- **Status codes:** 201; 404; 422 (`content` empty, or references a variable not declared in
  `variables[]`).
- **Note:** versions are immutable once created (per DB design §11) — there is deliberately no
  `PATCH` on a version; the only mutation is `activate`.

#### `POST /api/v1/prompt-templates/{templateId}/versions/{versionNumber}/activate`
- **Response `200`:** the now-active version; the previously active version's `is_active` flips to
  `false` in the same transaction (enforced by the DB's partial unique index, DB design §11).
- **Status codes:** 200; 404; 409 (version already active — idempotency short-circuit, not an error
  in practice but reported for clarity).

---

## 7. Evaluation Framework API

Owns `evaluations`, `evaluation_results`; reads `agent_runs`.

| Method | URI | Auth | Summary |
|---|---|---|---|
| GET | `/api/v1/agent-runs/{runId}/evaluations` | viewer | List evaluations for a run |
| POST | `/api/v1/agent-runs/{runId}/evaluations` | engineer / orchestrator | Trigger evaluator(s) against a run |
| GET | `/api/v1/evaluations/{evaluationId}` | viewer | Get an evaluation |
| GET | `/api/v1/evaluations/{evaluationId}/results` | viewer | List scored metrics |
| GET | `/api/v1/tasks/{taskId}/quality-gate` | viewer | Aggregated pass/fail across the task's latest run |

#### `POST /api/v1/agent-runs/{runId}/evaluations`
- **Request body:** `{ "evaluator_types": ["deepeval", "unit_test", "security_scan"] }`
- **Response `202`:** `{ "evaluation_ids": ["uuid", ...], "status": "queued" }` — one evaluation
  row per requested evaluator type, run in parallel by the Evaluation Framework's plugin runner.
- **Status codes:** 202; 404 (run not found); 422 (unknown `evaluator_type`, or run not yet
  `succeeded`).

#### `GET /api/v1/tasks/{taskId}/quality-gate`
- **Response `200`:** `{ "task_id", "agent_run_id", "overall": "passed|failed|pending", "evaluations": [{evaluator_type, status, results: [{metric_name, score, threshold, passed}]}] }`
- **Status codes:** 200; 404.
- This is the single call the Orchestrator (and the Dashboard's Evaluations screen) uses to decide
  whether a task may move to `awaiting_approval` — it exists so that logic lives in one place
  rather than being re-derived by every caller from raw `evaluation_results` rows.

---

## 8. Model Provider API

Admin surface over the Model Provider SDK's registered plugins (ADR-002). This API never proxies
an actual generation call — that happens internally between the Agent Orchestrator and the
provider plugin, not through a public HTTP surface, to avoid this API becoming a second (and
inconsistent) way to spend LLM budget outside the task/agent-run lifecycle.

| Method | URI | Auth | Summary |
|---|---|---|---|
| GET | `/api/v1/providers` | viewer | List registered providers |
| GET | `/api/v1/providers/{providerId}` | viewer | Get a provider's config/status |
| PATCH | `/api/v1/providers/{providerId}` | admin | Enable/disable, update default config |
| GET | `/api/v1/providers/{providerId}/models` | viewer | List models available from this provider |

#### `PATCH /api/v1/providers/{providerId}`
- **Request body:** `{ "is_enabled": true, "default_model": "string", "config": {} }`
- **Status codes:** 200; 403; 404; 422 (`config` fails the provider plugin's own schema —
  validated by delegating to that plugin, not hardcoded here, per the plugin-boundary principle).

---

## 9. Metrics API

Owns `metrics`; read-only surface (writes happen internally as agents/evaluations complete).

| Method | URI | Auth | Summary |
|---|---|---|---|
| GET | `/api/v1/metrics` | viewer | Query raw metric points |
| GET | `/api/v1/metrics/summary` | viewer | Aggregated metric summary |
| GET | `/api/v1/projects/{projectId}/metrics/summary` | viewer | Cost/latency/quality rollup for a project |

#### `GET /api/v1/metrics`
- **Query params:** `metric_name` (required), `entity_type`, `entity_id`, `recorded_at_from`,
  `recorded_at_to`, cursor pagination.
- **Response `200`:** cursor envelope of `{ metric_name, entity_type, entity_id, value, unit, recorded_at }`.
- **Status codes:** 200; 422 (`metric_name` missing — this endpoint refuses to return an unbounded
  full-table scan).

#### `GET /api/v1/metrics/summary`
- **Query params:** `metric_name` (required), `group_by` (`project`\|`agent`\|`provider`\|`day`),
  `recorded_at_from`, `recorded_at_to`, `agg` (`sum`\|`avg`\|`p95`, default `sum`).
- **Response `200`:** `{ "metric_name", "group_by", "agg", "buckets": [{ "key": "string", "value": number }] }`.
- **Status codes:** 200; 422 (`group_by`/`agg` not in the allowed set).

---

## 10. Audit API

Owns `audit_events`; read-only, compliance-facing.

| Method | URI | Auth | Summary |
|---|---|---|---|
| GET | `/api/v1/audit-events` | admin | Query the audit trail |
| GET | `/api/v1/audit-events/{eventId}` | admin | Get a single event |

#### `GET /api/v1/audit-events`
- **Query params:** `entity_type`, `entity_id`, `event_type`, `actor_user_id`, `actor_agent_id`,
  `created_at_from`, `created_at_to` (recommended, not required — but responses are capped and a
  warning header `X-Unbounded-Query: true` is returned if no date range is given), cursor
  pagination.
- **Response `200`:** cursor envelope of `AuditEvent` rows verbatim.
- **Status codes:** 200; 403 (non-admin).
- **Note:** this endpoint has no corresponding `POST`/`PATCH`/`DELETE` in the public API — writes
  only happen as a side effect of other endpoints, matching the DB design's "app role has INSERT
  only" rule (DB design §17).

---

## 11. Dashboard API

Composes the above; owns no domain data itself. Exists to give each Dashboard screen (per the
upcoming UX design doc) one call instead of N, not to duplicate the resource APIs above — the
Dashboard frontend is free to call §1–§10 directly for anything not listed here.

| Method | URI | Auth | Summary |
|---|---|---|---|
| GET | `/api/v1/dashboard/overview` | viewer | Home screen: active projects, running agents, recent evaluations, alerts |
| GET | `/api/v1/dashboard/projects/{projectId}/task-graph` | viewer | Full graph (tasks + dependencies + status + assigned agent) for graph rendering |
| GET | `/api/v1/dashboard/running-agents` | viewer | All currently `running`/`retrying` agent runs across projects the caller can see |

#### `GET /api/v1/dashboard/overview`
- **Response `200`:** `{ "active_projects": number, "running_agents": number, "pending_approvals": number, "recent_evaluations": [...], "recent_audit_events": [...] }`
- **Status codes:** 200.
- **Note:** this is a read-model assembled from §2/§5/§7/§10 server-side specifically so the
  Dashboard's home screen doesn't fan out to four APIs on every load; it is explicitly allowed to
  be a few seconds stale (cached, short TTL) since it's a summary view, not a source of truth.

---

## 12. Out of Scope Here

This document specifies REST contracts only. It does not define: the OpenAPI YAML/JSON document
itself (generated from these contracts, not hand-maintained separately), webhook/event payload
schemas beyond the SSE endpoint's event names, rate-limit thresholds per role, or the Agent SDK's
internal `plan()/execute()/evaluate()` interface that `POST /tasks/{taskId}/runs` triggers — that
belongs to the Agent SDK design doc.
