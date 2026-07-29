# context_builder — Context Builder

Turns a Task ID into a ranked, deduplicated, token-budgeted Context Package for an LLM call.
See `docs/architecture/06-context-builder.md` and `docs/architecture/04-api-design.md` §4.

## Status

Implemented: fourth full vertical slice.

- `domain/` — `SourceDocument`/`ContextPackage`/`ContextPackageSource`, `RankingWeights`, domain
  exceptions. Zero framework imports.
- `repository/` — SQLAlchemy models for `source_documents`/`context_packages`/
  `context_package_sources` (docs/architecture/03-db-design.md §12-13, §16). First module where
  two of its own tables (`context_packages` → `context_package_sources`) get a *real* FK to each
  other, since both are owned by this module — only `project_id`/`task_id` (owned by `projects`/
  `task_memory`) get the same deferred-FK treatment as every other cross-module reference.
- `services/` — `ContextBuilderService` (the Gather → Chunk → Dedup → Rank → Budget-fit →
  Assemble → Persist pipeline), `SourceDocumentIndexer` (a real local-filesystem gatherer),
  `JaccardSimilarityScorer` (the `semantic_similarity` signal and near-dup dedup, real token-
  overlap, no embedding model), `TextChunker` (real fixed-size sliding-window chunking).
- `api/` — all 5 endpoints from docs/architecture/04-api-design.md §4, wired into
  `aep.main:create_app()`.

## Cross-module boundaries

Resolving a task's project takes **two** hops through other modules' public `services/` (never
their `domain/`/`repository/`): `task_memory`'s `TaskService.get_task()` for `feature_id`, then
`projects`' `FeatureService.get_feature()` for `project_id`. Listing source documents for a
project also calls `projects`' `ProjectService.get_project()` first, to 404 on a project that
doesn't exist rather than silently returning an empty list. All three follow the same pattern as
`task_memory`'s call into `projects`' `FeatureService`: the target service's own documented
exception type is caught and translated into this module's local equivalent
(`TaskNotFoundError`/`FeatureNotFoundError`/`ProjectNotFoundError`).

## Scope: narrower than the full design doc, on purpose

docs/architecture/06-context-builder.md §13 itself puts "the embedding model or vector store" and
"the specific tokenizer integration per provider" out of scope for the *design* — no embedding
provider or real tokenizer is wired into `backend/` at all (the reference `ClaudeProvider` in
`examples/custom-provider-plugin` doesn't implement `embed()`). This reference implementation
builds everything the design doc leaves fully specified, and makes explicit, documented
simplifications everywhere it doesn't:

| Design doc concept | This implementation |
|---|---|
| `semantic_similarity` via embedding cosine similarity | `JaccardSimilarityScorer` — real word-token overlap between task text and chunk text. A classic-IR baseline, not a fake; swappable behind `TextSimilarityScorer` later. |
| Structural chunk boundaries (function/class/hunk) | Only the sliding-window fallback (`TextChunker`) — a real per-language structural splitter needs per-language parsing this module doesn't have. |
| 8 gatherer sources | Only 1 is real: `SourceDocumentIndexer` walks a local directory (e.g. a repo checkout on the same machine) and computes a real SHA-256 `content_hash` per file. Related PRs, the dependency graph, previous evaluations, and prompt templates are not gathered — see the table below. |
| `structural_proximity` (dependency-graph hop distance) | A documented constant stand-in (`STRUCTURAL_PROXIMITY_STUB`) — no dependency-graph gatherer exists to compute a real hop distance from. |
| `failure_history_boost` | A documented constant stand-in (`FAILURE_HISTORY_BOOST_STUB`) — the Evaluation Framework module (owner of `evaluations`/`evaluation_results`) doesn't exist in `backend/` yet. |
| Chunk-level persisted ranking (ADR-CB2) | Ranking/dedup run at real chunk granularity, but persistence rolls up to *document* granularity — this is what the design doc's own §10 "granularity reconciliation" already calls for (`relevance_score` = max across surviving chunks, `token_count` = sum of included chunks' tokens), not a deviation from it. |
| Exact tokenizer per provider (§8) | A char/4 heuristic (`estimate_tokens`), the same approximation and justification as `examples/custom-provider-plugin`'s `ClaudeProvider.count_tokens()`. No provider is registered in `backend/` yet to re-count against. |
| Async generation (`202` + pollable `job_id`) | Generation here has no embedding/LLM call in it, so it completes synchronously within the request. `job_id` in the response *is* the real `context_package_id` (fetchable immediately via `GET /context-packages/{id}`), and `status` is always `"completed"` — never a `"queued"` a caller would poll forever. |
| `POST .../context-packages`' `force_reindex` field | Accepted per the documented request shape, but a no-op: there's no per-project indexed-root-path configuration yet for a re-index to run against. |

## Known gaps, deliberate

- **Related pull requests, the dependency graph, previous evaluations, and prompt templates are
  not gathered.** Each needs a module or integration that doesn't exist in `backend/` yet: a real
  GitHub API integration (PRs), real import-graph static analysis (dependency graph), the
  Evaluation Framework module (`evaluations`/`evaluation_results`), and the Prompt Library module
  (`prompt_templates`/`prompt_versions`). `SourceDocumentIndexer` is the only real gatherer.
- **No indexing HTTP endpoint.** docs/architecture/04-api-design.md §4 doesn't define one —
  `source_documents` is described as populated by a background process the API only reads from
  (docs/architecture/06-context-builder.md §11). Call `SourceDocumentIndexer.index_directory()`
  directly (e.g. from a scheduled job or a repo webhook handler); the test suite does exactly
  this to seed fixtures.
- **No role enforcement yet** — same as every other module; `require_role()` exists and is
  proven inside the `auth` module's own endpoints only.
- **No FK from `source_documents.project_id`/`context_packages.task_id`** to their owning
  tables — same cross-module `create_all()` ripple reason as every other module's deferred FKs
  (see `modules/projects/README.md`'s note on `owner_user_id`). `context_package_sources`' FKs
  to `context_packages`/`source_documents` *are* real, since this module owns both.
- **No Alembic migration yet** — same as every other module.

## Tests

- `tests/unit/modules/context_builder/{domain,repository,services}/` — SQLite-backed, no
  network; `services/test_indexing.py` and `services/test_context_builder_service.py` operate on
  real temporary directories and real file content (no mocked filesystem).
- `tests/integration/test_context_builder_api.py` — full HTTP lifecycle: generate → get →
  history → sources → project source-document listing, plus the 404/422 cases. Seeds
  `source_documents` by calling `SourceDocumentIndexer` directly against the same test database
  (no indexing endpoint exists to call over HTTP — see "Known gaps" above).
