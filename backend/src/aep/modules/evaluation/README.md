# evaluation — Evaluation Framework (host side)

Runs the pluggable quality gate (DeepEval, Promptfoo, LLM-judge, unit tests, static analysis,
security scans, etc.) against agent output before it's eligible for human approval. Evaluator
plugins themselves live behind `sdk/aep-eval-sdk`. See `docs/architecture/07-evaluation-framework.md`.
