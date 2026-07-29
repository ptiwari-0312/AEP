# auth — Authentication Service

OAuth/JWT identity, RBAC, and the audit-event source of truth for "who did what."
See `docs/architecture/04-api-design.md` §1, §10.

## Status

Implemented: third full vertical slice, and the module `core/security.py` and both existing
modules' placeholder authentication were waiting on.

- `domain/` — `User`/`Role`/`UserRole`/`RefreshToken`/`AuditEvent`, domain exceptions.
- `repository/` — SQLAlchemy models for `users`/`roles`/`user_roles`/`refresh_tokens`/
  `audit_events` (docs/architecture/03-db-design.md §1-2, §16, §17). First use of a composite
  primary key (`user_roles`) and a JSON column (`audit_events.payload`, JSONB on Postgres via
  `.with_variant()`, generic JSON elsewhere) in this codebase.
- `services/` — `AuthService` (login/refresh/logout, with refresh-token rotation on every use),
  `UserService` (user CRUD + role grant/revoke), `AuditService`, and an `OAuthProvider`
  abstraction with a real `GitHubOAuthProvider` (actual HTTP calls to GitHub's token/user
  endpoints, tested against a mocked transport — no live credentials needed). Google/Okta are
  named in the API contract but have no registered provider; `AuthService` raises
  `UnsupportedOAuthProviderError` (422) rather than faking them.
- `api/` — all endpoints from docs/architecture/04-api-design.md §1 and §10.
- **`aep/core/security.py`** (not this module, but built alongside it) — JWT issuance/
  verification and the `get_current_user`/`get_current_user_id`/`require_role()` dependencies
  every other module's `api/` layer uses. Roles are carried as a JWT claim, resolved once at
  login/refresh — an authorization check anywhere else in the app is a pure JWT decode, never a
  DB round trip (trade-off: a role change doesn't take effect until the user's token is next
  refreshed).

## Follow-through on the two modules that were waiting on this

- `modules/projects/api/dependencies.py` and `modules/task_memory/api/dependencies.py` now
  import the real `get_current_user_id` from `aep.core.security` instead of their local
  placeholders — every endpoint in both modules now requires a real bearer token. Their
  integration tests were updated to log in via a fake OAuth provider
  (`dependency_overrides[get_oauth_providers]`) first.
- **Not done, deliberately:** neither module's endpoints enforce specific roles yet (e.g.
  `POST /projects` should require `engineer`, `POST /projects/{id}/archive` should require
  `engineer`-owner-or-`admin`). `core/security.py`'s `require_role()` exists and is proven inside
  this module's own admin endpoints, but retrofitting it across ~19 already-shipped endpoints in
  two other modules — including the judgment call of what "viewer" should mean for a user who
  only holds `engineer` (see note below) — is its own follow-up, not folded into this pass.
- **Still no FK from `projects.owner_user_id`/`features.created_by`/
  `execution_history.changed_by_user_id` to `users.id`**, even though `users` exists now — see
  the comment in `modules/projects/repository/models.py` for why (a live cross-module FK means
  every existing test that calls `Base.metadata.create_all()` would need to import this
  module's models too, just to resolve the reference; a real Alembic migration is the right
  place to add it, not a mechanical ripple across two modules' test suites).

## A design judgment call worth flagging

The API design doc states roles as `viewer`/`engineer`/`reviewer`/`admin` with only one stated
inheritance rule: "admin satisfies any lower requirement." Taken completely literally, an
`engineer` user with no `viewer` grant couldn't pass a `require_role("viewer")` check — which
would make basic reads impractical for anyone who isn't also explicitly given `viewer`. Read-only
endpoints in this module (`GET /users/me`, `GET /roles`) are gated with plain
`Depends(get_current_user)` — any authenticated user, regardless of role — rather than
`require_role("viewer")`, treating "viewer" as the authenticated floor rather than a specific
grant every other role must separately hold.

## Known gaps, deliberate

- **No Google/Okta OAuth provider.** Named in the API contract, not implemented — see above.
- **No Alembic migration yet** — same as the other two modules; schema exists only as
  SQLAlchemy models, exercised via `Base.metadata.create_all()` against SQLite in tests.
- **No automatic audit-event writing from other modules' mutating endpoints.** Only this
  module's own login flow calls `AuditService.record_event()`, to prove the write path
  end-to-end. Wiring Project Service's/Task Memory Service's create/update/transition endpoints
  to also record audit events is a deliberately separate follow-up — see `AuditService`'s
  docstring.

## Tests

- `tests/unit/modules/auth/{domain,repository,services}/` — SQLite-backed, no network. The
  `GitHubOAuthProvider` tests use `httpx.MockTransport` against GitHub's real request/response
  shapes (including the private-email fallback to `/user/emails`).
- `tests/integration/test_auth_api.py` — full HTTP lifecycle: login → `/users/me` → RBAC 403 →
  admin grant/revoke roles → refresh rotation → logout → revoked-token reuse rejected → audit
  event query.

## A real bug found and fixed while building this

`RefreshToken.expires_at` is computed as a timezone-aware UTC `datetime`, but SQLite silently
drops `tzinfo` on round trip through SQLAlchemy's `DateTime` type (confirmed empirically — a
tz-aware datetime comes back naive). Comparing the DB-round-tripped value directly against a
freshly-computed `utcnow()` raised `TypeError: can't compare offset-naive and offset-aware
datetimes`. Fixed with `aep.core.db.ensure_utc()`, which treats a naive datetime as UTC-by-
convention rather than local time, so the comparison works regardless of which side of it went
through a database round trip.
