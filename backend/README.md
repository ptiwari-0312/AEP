# aep-backend

The modular monolith: one deployable FastAPI app composed of the modules under `src/aep/modules/*`.
Structure and dependency rules are defined in
[`docs/architecture/02-repo-design.md`](../docs/architecture/02-repo-design.md) §2 and enforced per
[`docs/architecture/09-engineering-standards.md`](../docs/architecture/09-engineering-standards.md).

Depends on `aep-provider-sdk`, `aep-agent-sdk`, and `aep-eval-sdk` from `../sdk/`; never the
reverse.

Currently structure-only — no module has an implementation yet.
