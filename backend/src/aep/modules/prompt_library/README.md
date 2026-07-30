# prompt_library — Prompt Library

Versioned, testable prompt templates consumed by agents; decouples prompt iteration from agent
code changes. See `docs/architecture/04-api-design.md` §6 and
`docs/architecture/09-engineering-standards.md` §9.

## Status

Implemented: seventh full vertical slice, and the simplest one so far — fully self-contained,
no cross-module calls at all.

- `domain/` — `PromptTemplate`/`PromptVersion`/`PromptVariable`, plus `rendering.py`'s pure
  `extract_referenced_variables()`/`validate_variables_declared()`/`render()` functions, and
  domain exceptions.
- `repository/` — SQLAlchemy models for `prompt_templates`/`prompt_versions`
  (docs/architecture/03-db-design.md §10-11), including a **real** partial unique index
  (`sqlite_where`/`postgresql_where`) enforcing "at most one active version per template" at the
  database level — docs/architecture/09-engineering-standards.md §9 names this constraint
  explicitly as what enforces the rule, not application code, so it's implemented as a real
  constraint and proven with a test that bypasses the service layer's own sequencing entirely.
- `services/` — `PromptLibraryService`: one combined service for both tables (same shape as
  `evaluation.EvaluationService` handling `evaluations`+`evaluation_results`), since a version is
  never addressed except through its parent template.
- `api/` — all 7 endpoints from docs/architecture/04-api-design.md §6, wired into
  `aep.main:create_app()`.

## No cross-module collaborators

Unlike every other module built so far, this one talks to nothing else: `owner_user_id`/
`created_by` are `UUID`s obtained from the caller (`aep.core.security.get_current_user_id`),
never resolved against `auth`'s `users` table (same deferred-FK stance every other module takes
on `owner_user_id`-style columns), and nothing else in the schema references
`prompt_templates`/`prompt_versions` from *this* side — `agent_runs`/`context_packages` reference
`prompt_template_id`/`prompt_version_number` optionally (docs/architecture/03-db-design.md §9,
§12), but nothing in this module needs to know that.

## A real capability beyond the literal API surface: `render()`

docs/architecture/09-engineering-standards.md §9 is explicit that "a prompt referencing a
variable not declared, or a caller omitting a required one, fails at **activation/render** time" —
two distinct failure points, not one. The API design doc's endpoint list only covers the
activation-time check (`POST .../versions`'s 422 for an undeclared reference). Render-time
validation — a caller omitting a required variable — has no HTTP endpoint in the documented
contract (there's no `POST .../render`), but the standards doc still calls for the capability to
exist, so `PromptLibraryService.render_version()` is real and tested even though nothing in
`api/router.py` calls it yet. It's there for another module (a future real, provider-backed agent
implementation, replacing `orchestrator`'s current `EchoAgent`) to call once it needs to turn a
template + variable values into the actual text sent to a model.

Placeholder syntax is `{{ name }}` — a reference implementation's own concrete choice for an
otherwise-unspecified detail (neither design doc picks one), implemented as a plain regex
substitution, not a template-engine dependency. An optional variable with no supplied value is
left as its literal `{{name}}` placeholder in rendered output, rather than silently blanked to an
empty string.

## Known gaps, deliberate

- **No role enforcement yet** — same as every other module.
- **No FK from `owner_user_id`/`created_by` to `users.id`** — same cross-module `create_all()`
  ripple reason as every other module's deferred FKs. `prompt_versions.prompt_template_id ->
  prompt_templates.id` *is* a real FK, since both are owned by this module.
- **No Alembic migration yet** — same as every other module. The partial unique index above is
  expressed as SQLAlchemy `Index(..., sqlite_where=..., postgresql_where=...)` against
  `Base.metadata`, not yet as a generated migration.
- **List endpoints don't inline the active version** — only `GET /prompt-templates/{templateId}`
  (the single-template fetch) includes `active_version` inline, matching the API design doc's
  precise wording ("Get a template (+ active version inline)"); `GET /prompt-templates` (the list)
  omits it per template to avoid an N+1 query per page, a scope choice the doc doesn't contradict
  since it never mentions inlining it in the list response.

## Tests

- `tests/unit/modules/prompt_library/{domain,repository,services}/` — SQLite-backed, no network.
  `repository/test_prompt_version_repository.py` includes a test that bypasses
  `PromptLibraryService`'s own deactivate-then-activate ordering and inserts two `is_active=true`
  rows for the same template directly, expecting the database itself (`IntegrityError`) to reject
  the second one.
- `tests/integration/test_prompt_library_api.py` — full HTTP lifecycle: create template → create
  version → activate → create+activate a second version → reactivate the first → the already-
  active 409 short-circuit, plus the 404/422/409 cases.
