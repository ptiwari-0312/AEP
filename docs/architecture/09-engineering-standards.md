# AEP — Engineering Standards

> Produced from `prompts/prompt9-CodingStd.md`. This document is binding: every future code
> change to this platform — human- or agent-authored — must conform to it. Where it restates a
> rule from an earlier design doc, that doc is the source of the *rationale*; this doc is the
> source of the *rule* in enforceable form. Where the two ever disagree, fix the disagreement
> rather than picking one silently.

## 0. Enforcement

A standard that isn't checked isn't a standard, it's a suggestion. Each section below ends with
an **Enforced by** line naming the mechanism — CI lint, type check, import-boundary check, or PR
review — so nothing here is aspirational-only. New rules added to this doc later must come with
an enforcement mechanism, not just a sentence.

## 1. Architecture Principles

Restates [01-vision-and-principles.md](01-vision-and-principles.md) §2–3 as binding rules:

- No module may import a specific LLM provider's SDK directly — only through the Model Provider
  SDK interface (ADR-002).
- No module under `backend/modules/*` may import another module's `domain/` or `repository/`
  layer directly (repo design §2).
- Every agent lifecycle transition and every mutating cross-module effect goes through a domain
  event (ADR-004) or a module's public `services/` interface — never a direct DB read across
  module boundaries.
- A new capability is added as a plugin (agent, evaluator, provider) wherever one of those three
  plugin systems already exists for that kind of capability — a new `if provider == "x"` branch
  anywhere outside `providers/` is a standards violation, not a shortcut.

**Enforced by:** import-boundary linter (e.g. `import-linter`/`dependency-cruiser`-equivalent)
running in CI against the contracts in §4; PR review for the "use the plugin system" judgment call.

## 2. Folder Structure

The canonical tree is [02-repo-design.md](02-repo-design.md) §1–§8 — this doc does not repeat it.
Two binding additions:

- A new top-level folder requires an update to that repo design doc in the same PR that adds it —
  structure changes are architecture changes, not incidental.
- Within `backend/modules/<name>/`, the `api/ → domain/ → services/ → repository/` shape (repo
  design §2) is mandatory for every module, including new ones added later; there is no "simple
  module" exception that collapses the layers.

**Enforced by:** PR review; a CI check that `backend/modules/*` subfolders match the expected set.

## 3. Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Python module/file | `snake_case.py` | `agent_runs.py` |
| Python class | `PascalCase` | `CodingAgent`, `BaseEvaluator` |
| Python function/variable | `snake_case` | `assign_agent_to_task()` |
| Python constant | `UPPER_SNAKE_CASE` | `MAX_RETRY_ATTEMPTS` |
| Python private member | leading underscore | `_internal_state` |
| TypeScript component file | `PascalCase.tsx` | `TaskGraphCanvas.tsx` |
| TypeScript hook | `useCamelCase.ts` | `useAgentRunEvents.ts` |
| TypeScript non-component module | `camelCase.ts` | `apiClient.ts` |
| DB table | `snake_case`, plural | `agent_runs`, `task_dependencies` |
| DB column | `snake_case` | `assigned_agent_id` |
| REST URI segment | `kebab-case`, plural nouns | `/context-packages`, `/prompt-templates` |
| Domain event name | `dot.case`, `entity.verb_past_tense` | `agent_run.completed`, `evaluation.failed` |
| Environment variable | `AEP_UPPER_SNAKE_CASE` | `AEP_DATABASE_URL` |
| SDK package import name | `aep_<kind>_sdk` | `aep_provider_sdk`, `aep_agent_sdk` |

**Enforced by:** linter naming-convention rules (`ruff`/`eslint`) where mechanically checkable;
PR review for domain event names and anything semantic.

## 4. Dependency Rules

Restates and makes binding [02-repo-design.md](02-repo-design.md) §9's dependency graph:

- `sdk/*` depends on nothing under `backend/`, `frontend/`, or `infra/`. A single violation here
  breaks the entire "plugin authors never see internals" guarantee — this is the one rule in this
  document with zero tolerance for exceptions.
- `backend/modules/*` depend on `core/` and `sdk/*` interfaces; never on another module's
  internals (§1).
- `frontend/src/features/*` depend on `components/` and the generated `api-client/`; never on
  another `features/*` folder directly (repo design §4).
- `examples/*` depend only on `sdk/*` — if an example ever needs a `backend/` import to compile,
  the SDK interface is incomplete, and that's a bug in the SDK, not in the example.

**Enforced by:** CI import-boundary check (fails the build on violation, not just a warning);
`examples/*` are built in CI against the current SDK version as a boundary-integrity check
(repo design §7).

## 5. Logging Standards

- All logs are structured (JSON in production, human-readable in local dev), emitted through
  `core/observability`, never `print()`.
- Every log line automatically carries: `timestamp`, `level`, `module`, `trace_id`/`span_id`
  (OpenTelemetry context), and — when applicable — `agent_run_id`/`task_id` (Agent SDK §9 already
  guarantees this inside `BaseAgent.run()`; the same binding applies to any other request-scoped
  code path via a logging context manager in `core/observability`).
- Log level guide: `DEBUG` for step-level detail useful only when actively debugging; `INFO` for
  one line per meaningful state transition (task status change, agent run start/end); `WARNING`
  for a recovered/retried failure; `ERROR` for a failure that surfaces to a caller or ends a run.
- **Never log:** raw JWTs/API keys/secrets, full LLM prompt/response bodies containing customer
  data (log a reference — e.g. `context_package_id` — not the content), or full `payload` blobs
  from `audit_events` at `INFO` (they're queryable via the Audit API when needed; routine logging
  shouldn't duplicate that store).

**Enforced by:** PR review; a log-scanning CI check (regex for common secret shapes) as a backstop,
not the primary control.

## 6. Exception Handling

- A single exception hierarchy rooted at `AEPError`, with module-specific subclasses
  (`ProjectServiceError`, `ContextBuilderError`, etc.) and the retryable/terminal split already
  established for agents and evaluators generalized platform-wide:
  `AEPRetryableError` / `AEPTerminalError` as the two direct children most module errors should
  eventually derive from.
- `core/errors.py` owns the one mapping from exception type → HTTP status/Problem-Details `type`
  URI (API design §0.6) — individual `api/` routers catch nothing they don't add specific context
  to; they let `AEPError` subclasses propagate to a single exception handler.
- Never catch a bare `except Exception` to suppress a failure silently — catch the specific type
  you can meaningfully handle, or let it propagate. A caught-and-logged-only exception at `ERROR`
  is acceptable at a process boundary (e.g. the top of an agent's `run()` loop); it is not
  acceptable mid-function as a substitute for handling the case.
- Every raised domain exception includes enough structured context (the relevant `task_id`,
  `agent_run_id`, etc.) to be actionable from a log line alone, without needing a debugger session.

**Enforced by:** PR review; a lint rule banning bare `except:`/`except Exception:` without
re-raise or explicit justification comment.

## 7. API Design

Binding restatement of [04-api-design.md](04-api-design.md) §0: URI versioning (`/api/v1/`), RFC
7807 error bodies, the two pagination styles chosen per access pattern, and role requirements
stated explicitly per endpoint. One addition: **the OpenAPI document is generated from route
definitions, and a PR that changes an endpoint's shape without a corresponding OpenAPI diff fails
review** — `frontend/api-client` and the SDK examples both depend on that document staying honest.

**Enforced by:** CI step that regenerates the OpenAPI doc and fails if it differs from the
committed version; PR review for new-endpoint role/error correctness.

## 8. Testing Strategy

- Test pyramid, matching [02-repo-design.md](02-repo-design.md) §2's three suites: unit tests
  (majority, no DB/network, mirror `src/` structure) → integration tests (real DB, mocked
  providers) → e2e tests (a handful, covering the full Create-Project-to-Merge pipeline from the
  vision doc, not every permutation).
- Test naming: `test_<unit_under_test>_<behavior>` — e.g.
  `test_task_status_transition_rejects_illegal_edge`. A test name should make the failure
  meaningful from a CI log alone.
- `domain/` layers are unit-tested with zero fixtures beyond plain Python objects (Agent SDK-style
  layers have no framework imports, per repo design §2, specifically so this is possible).
- Every new evaluator or agent plugin ships with: a unit test of its `score()`/`evaluate()` logic
  against fixed fake input, and an entry in `examples/` if it's meant to demonstrate the SDK
  boundary (repo design §7).
- Coverage is tracked as an **informational** metric (Evaluation Framework §7's
  required-vs-informational distinction applies to the platform's own CI, not just agent output) —
  a coverage dip is visible and discussed, not an automatic merge block, because a hard coverage
  gate incentivizes low-value tests written to hit a number.

**Enforced by:** CI runs all three suites on every PR (unit+integration required to pass; e2e
required on merge to main); coverage reported, not gated.

## 9. Prompt Engineering Standards

- Prompts are never hardcoded as string literals inside agent code — they live exclusively in the
  Prompt Library (`prompt_templates`/`prompt_versions`, DB design §10–11) and are loaded by
  `template_id` + active version at run time. An agent's `plan()`/`execute()` referencing an
  inline prompt string is a standards violation, not a style preference — it's exactly the
  prompt/agent-code coupling the Prompt Library module exists to prevent (vision doc §4).
- Every prompt template declares its `variables` explicitly (name + required flag, DB design §11);
  a prompt referencing a variable not declared, or a caller omitting a required one, fails at
  activation/render time, not silently at generation time with a malformed prompt.
- Prompt versions are immutable once created (DB design §11) — iterate by creating a new version
  and activating it, never by editing existing prompt text in place, so any past `agent_run` or
  `evaluation` remains reproducible against the exact prompt that produced it.
- A prompt template change goes through the same review expectation as a code change: the diff
  between versions (Dashboard §9) is the review artifact.

**Enforced by:** the DB's partial-unique-active-version constraint (DB design §11) and
`variables` validation at the API layer; PR review is not the primary control here since prompt
edits happen through the Prompt Library UI/API, not a code PR — this is itself a deliberate
design choice so prompt iteration doesn't require a deploy.

## 10. Agent Development Guidelines

- Every agent subclasses `BaseAgent` (Agent SDK §2) and implements exactly the four hooks —
  `plan`, `execute`, `evaluate`, `report`. `run()`, `cancel()`, `retry()`, `heartbeat()` are never
  overridden; if a new agent type seems to need different lifecycle behavior, that's a signal to
  extend `BaseAgent` for everyone, not to override it in one subclass.
- `execute()` must poll its `CancellationToken` at every safe checkpoint (Agent SDK §7) — a loop
  over multiple tool calls or file edits with no checkpoint in between is a standards violation
  even if it happens to run fast in practice.
- Tool execution (shell, file I/O, static-analysis binaries) happens only inside the assigned
  sandbox — never a direct subprocess call from within the Orchestrator's own process (Agent SDK
  §11).
- Logging and metrics go through `self.log`/`self.emit_metric` (Agent SDK §9–10), never a
  module-level logger instantiated inside the agent — the base-class binding of
  `agent_run_id`/`task_id`/trace context only happens through those.

**Enforced by:** PR review against the Agent SDK contract; a runtime assertion in `BaseAgent.run()`
that rejects an agent instance overriding a final method (fails fast at registration, not at
first run).

## 11. Plugin Development Guidelines

Applies uniformly to the three plugin systems (providers, agents, evaluators):

- Each plugin declares its own config schema and validates its own config — the host (Orchestrator,
  Evaluation Runner) never hand-rolls per-plugin-type validation (API design §8, Evaluation
  Framework §8).
- Each `sdk/aep-*-sdk` package is independently versioned (semver); a breaking change to a base
  interface is a major version bump and requires updating every in-repo plugin and the matching
  `examples/*` entry in the same PR — an SDK breaking change with no updated example is treated as
  incomplete, not merged with a follow-up ticket.
- A plugin registers itself at boot via the relevant registry (`backend/plugins`) and upserts its
  catalog row (`agents`/`providers`/evaluator registration) idempotently — re-registration on
  every restart must not create duplicate catalog entries.

**Enforced by:** CI build of `examples/*` against the current SDK version (repo design §7); PR
review for config-schema completeness.

## 12. Documentation Standards

- Code comments follow the platform-wide default already in effect for this project: none, unless
  the comment captures a non-obvious *why* (a workaround, a hidden constraint, a surprising
  invariant) that the code itself can't express — never a comment restating what well-named code
  already shows.
- Architecture-level decisions (this design series) are numbered and additive — a superseded
  decision gets a new numbered doc noting the supersession, it does not silently overwrite or
  delete the old one, so the history of *why* remains readable.
- Every module (`backend/modules/<name>/`, each `sdk/aep-*-sdk/`) has one `README.md` covering: its
  responsibility (one paragraph, matching vision doc §4's shape), its public interface, and any
  config it needs — kept short enough that it stays accurate; a README that duplicates this design
  series is a README that will rot.
- Public SDK interfaces (`sdk/*`) carry docstrings on every public method describing the contract
  (inputs, outputs, error conditions) — this is the one place docstrings are mandatory rather than
  WHY-only, because external plugin authors have no other source for the contract.

**Enforced by:** PR review; a CI check that each `backend/modules/*` and `sdk/aep-*-sdk/` folder
contains a `README.md`.

## 13. Security Standards

- Secrets (provider API keys, DB credentials, JWT signing keys) are never committed, never logged
  (§5), and never included in a Context Package sent to an LLM — the Context Builder's gatherers
  (§06-context-builder.md §3) operate only over `source_documents`, which by construction never
  ingests credential files.
- RBAC is enforced server-side on every mutating endpoint (API design §0.2) — the Dashboard hiding
  a control (Dashboard UX §2) is a UX nicety, never the actual access control.
- Tool execution for agents and deterministic evaluators is always sandboxed (Agent SDK §11,
  Evaluation Framework §6) — no exception for "trusted" agent types, since the sandbox boundary
  exists for agent-produced *code*, not agent *intent*.
- The application's DB role has `INSERT`-only privilege on `audit_events` and `execution_history`
  (DB design §17) — least-privilege at the database layer, not only at the application layer, so
  an application-level bug can't silently rewrite history.
- Dependencies (Python, npm) are scanned in CI for known vulnerabilities on every PR; a new
  dependency in `sdk/*` gets extra scrutiny in review since it becomes a transitive dependency for
  every plugin author.
- All external input (API request bodies, webhook payloads from Braintrust/Langfuse) is validated
  against a schema at the boundary (§0.7 of the API design) before touching any business logic —
  never trust a payload's shape because it came from a "trusted" external platform.

**Enforced by:** CI dependency scanning; CI import-boundary check covers the sandbox-bypass case
mechanically (tool-execution modules are only importable from within sandbox-entry code paths);
PR review for the rest.

## 14. Enforcement Summary

| Mechanism | What it catches |
|---|---|
| CI import-boundary check | `sdk/*` purity, module/module and feature/feature isolation, sandbox-only tool execution |
| CI type check + lint | naming conventions, bare-except bans, log-secret regex backstop |
| CI test suites (unit/integration/e2e) | behavioral correctness per §8 |
| CI OpenAPI diff check | API contract drift |
| CI `examples/*` build | SDK boundary integrity, breaking-change completeness |
| CI dependency scan | known-vulnerability introduction |
| DB constraints | prompt-version immutability/single-active, audit/history append-only |
| PR review | everything requiring judgment: plugin-vs-shortcut calls, config-schema completeness, documentation quality |

## 15. Out of Scope Here

This document is the binding standards reference; it is not itself a tutorial. Onboarding
material, IDE setup, and local dev environment bootstrap belong in each package's `README.md`
(§12), not here.
