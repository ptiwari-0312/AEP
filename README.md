# AEP — Agentic Engineering Platform

An enterprise-grade, vendor-neutral platform that standardizes how engineering teams use AI
coding agents across the SDLC: `Project → Feature → Task Graph → Agent Assignment → Context
Generation → Code Generation → Evaluation → Human Approval → Merge`.

Not tied to Claude, OpenAI, Gemini, or Vertex AI specifically — all are pluggable providers behind
one interface.

## Documentation

The full architecture is in [`docs/architecture/`](docs/architecture/), numbered and sequential:

| Doc | Covers |
|---|---|
| [01-vision-and-principles.md](docs/architecture/01-vision-and-principles.md) | Vision, principles, ADRs |
| [02-repo-design.md](docs/architecture/02-repo-design.md) | This repository's structure |
| [03-db-design.md](docs/architecture/03-db-design.md) | Database schema + ER diagram |
| [04-api-design.md](docs/architecture/04-api-design.md) | REST API contracts |
| [05-agent-sdk.md](docs/architecture/05-agent-sdk.md) | Agent plugin interface |
| [06-context-builder.md](docs/architecture/06-context-builder.md) | Context ranking/budgeting algorithm |
| [07-evaluation-framework.md](docs/architecture/07-evaluation-framework.md) | Evaluator plugin architecture |
| [08-dashboard-ux.md](docs/architecture/08-dashboard-ux.md) | Dashboard UX specification |
| [09-engineering-standards.md](docs/architecture/09-engineering-standards.md) | Binding engineering standards |

## Repository Layout

```
backend/    modular monolith (FastAPI) — one deployable
sdk/        publishable plugin-interface packages (provider, agent, evaluator)
frontend/   React + TypeScript dashboard
infra/      Docker, Kubernetes, observability config
docs/       architecture, API specs, ADRs, runbooks
examples/   reference plugins built against the SDKs
scripts/    repo-local dev/CI tooling
```

See [02-repo-design.md](docs/architecture/02-repo-design.md) for the full structure and dependency
rules.

## Status

Architecture design complete; repository structure scaffolded. No modules are implemented yet.
