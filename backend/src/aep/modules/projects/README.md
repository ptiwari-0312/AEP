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

- **Real authentication is wired in now** (`aep.core.security.get_current_user_id`, built
  alongside the `auth` module) — the previous placeholder is gone, and nothing in this module's
  request/response shapes had to change to make that swap, as planned.
- **Still no FK from `owner_user_id`/`created_by` to `users.id`**, even though `users` exists
  now — see the comment on `ProjectModel.owner_user_id` in `repository/models.py` for why: a
  live cross-module FK means every test in *both* modules that calls
  `Base.metadata.create_all()` would need to import the `auth` module's models too, just to
  resolve the reference. A real Alembic migration is the right place for this, not a mechanical
  import ripple across dozens of test fixtures.
- **No role enforcement yet** (`POST /projects` should require `engineer`,
  `POST /projects/{id}/archive` should require `engineer`-owner-or-`admin`, per
  docs/architecture/04-api-design.md §2). `core/security.py`'s `require_role()` exists and is
  proven inside the `auth` module's own endpoints; retrofitting it here is a deliberately
  separate follow-up — see `modules/auth/README.md`.
- **No Alembic migration yet** — the schema exists only as SQLAlchemy models, exercised via
  `Base.metadata.create_all()` against SQLite in tests. Generating a real migration needs a
  Postgres instance to autogenerate against.

## Tests

- `tests/unit/modules/projects/{domain,repository,services}/` — SQLite-backed, no network.
- `tests/integration/test_projects_api.py` — full HTTP lifecycle (create → update → attach
  repo → create feature → transition → archive → 404/409 cases) through the real FastAPI app.

