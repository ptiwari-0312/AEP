# aep-backend

The modular monolith: one deployable FastAPI app composed of the modules under `src/aep/modules/*`.
Structure and dependency rules are defined in
[`docs/architecture/02-repo-design.md`](../docs/architecture/02-repo-design.md) §2 and enforced per
[`docs/architecture/09-engineering-standards.md`](../docs/architecture/09-engineering-standards.md).

Depends on `aep-provider-sdk`, `aep-agent-sdk`, and `aep-eval-sdk` from `../sdk/`; never the
reverse.

## Status

`core/` is implemented (`config.py`, `db.py`, `errors.py`, `events.py`, `observability.py`) —
see `src/aep/core/` and `tests/unit/core/`. Notably, `events.py`'s `RedisEventPublisher`/
`InMemoryEventPublisher` and `observability.py`'s `OpenTelemetryMetricsSink` satisfy the
`EventPublisher`/`MetricsSink` `Protocol`s independently declared in each of `aep-agent-sdk`,
`aep-eval-sdk`, and `aep-provider-sdk` — via structural typing, with zero import of any of
those packages, proving the "sdk/* depends on nothing under backend/, and backend/ needs no
special-casing per SDK" design actually holds (docs/architecture/02-repo-design.md §9).

`core/security.py` (JWT/RBAC) is deliberately not built yet — it depends on the `auth` module's
user model, which doesn't exist. `modules/*` are still empty placeholders.

## Dev

```
pip install -e ../sdk/aep-agent-sdk -e ../sdk/aep-eval-sdk -e ../sdk/aep-provider-sdk
pip install -e ".[dev]"
pytest tests/unit
```

