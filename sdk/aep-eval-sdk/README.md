# aep-eval-sdk

The `BaseEvaluator` contract every evaluator type implements (`prepare`/`execute`/`score`/`report`).
See `docs/architecture/07-evaluation-framework.md`. `backend/` and every evaluator plugin depend on
this package; this package depends on nothing in `backend/`.

Currently structure-only — `BaseEvaluator` itself is not yet implemented.
