# projects — Project Service

Owns Projects, Features, and Git Repositories: the durable, human-authored intent everything
else executes against. See `docs/architecture/01-vision-and-principles.md` §4 and
`docs/architecture/04-api-design.md` §2.

## Status

Implemented, first full vertical slice of the platform:

- `domain/` — `Project`/`Feature`/`GitRepository` dataclasses, the feature status state
  machine (`is_legal_feature_transition`), and domain exceptions. Zero framework imports.
- `repository/` — SQLAlchemy models for `projects`/`features`/`git_repositories`
  (docs/architecture/03-db-design.md §3-5) and repository classes.
- `services/` — `ProjectService`/`FeatureService`: slug-uniqueness, archive-idempotency, and
  the feature status transition rule.
- `api/` — all 11 endpoints from docs/architecture/04-api-design.md §2, wired into
  `aep.main:create_app()`.

## Known gaps, deliberate

- **No FK from `owner_user_id`/`created_by` to `users.id`.** The `auth` module, which owns
  that table, doesn't exist yet. Add the constraint once it does
  (docs/architecture/03-db-design.md §4).
- **No real authentication.** `api/dependencies.py:get_current_user_id()` returns a fixed
  placeholder UUID. Request bodies deliberately don't accept an owner/creator field (matching
  the documented API contract) — replace the dependency with a real JWT-derived one once
  `core/security.py` and the `auth` module exist; nothing else in this module should need to
  change.
- **No Alembic migration yet** — the schema exists only as SQLAlchemy models, exercised via
  `Base.metadata.create_all()` against SQLite in tests. Generating a real migration needs a
  Postgres instance to autogenerate against.

## Tests

- `tests/unit/modules/projects/{domain,repository,services}/` — SQLite-backed, no network.
- `tests/integration/test_projects_api.py` — full HTTP lifecycle (create → update → attach
  repo → create feature → transition → archive → 404/409 cases) through the real FastAPI app.

