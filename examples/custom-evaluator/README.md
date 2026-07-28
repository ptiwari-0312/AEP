# custom-evaluator — UnitTestEvaluator

A reference evaluator plugin built against `sdk/aep-eval-sdk`
(see [docs/architecture/07-evaluation-framework.md](../../docs/architecture/07-evaluation-framework.md)),
proving that an evaluator can be built depending on nothing but that SDK
([docs/architecture/02-repo-design.md](../../docs/architecture/02-repo-design.md) §7).

## What it does

`UnitTestEvaluator` runs `pytest` as a subprocess against a target project, parses the JUnit XML
report it produces, and scores two metrics:

- `pass_rate` — `(total - failed) / total`, gated against `min_pass_rate`
- `failures` — raw failed+errored test count, gated at zero

The subprocess is invoked with `--confcutdir`/`--rootdir` pinned to the target directory so it
never picks up this package's own `pyproject.toml`/`conftest.py` — the evaluator's own test suite
runs pytest *on* a fixture project (`tests/fixtures/sample_project/`) from *within* a pytest run of
its own, and the two must not interfere with each other.

## Config

| Field | Default | Meaning |
|---|---|---|
| `working_directory` | `"."` | Fallback target directory if `agent_run.metadata["repo_path"]` isn't set |
| `test_path` | `"tests"` | Path (relative to the working directory) passed to pytest |
| `pytest_args` | `[]` | Extra CLI args forwarded to pytest, e.g. `["-k", "some_filter"]` |
| `min_pass_rate` | `1.0` | Threshold for the `pass_rate` metric |
| `timeout_seconds` | `120.0` | Kills the subprocess if it runs longer than this |

`agent_run.metadata["repo_path"]`, when present, overrides `working_directory` — this is how the
Agent Orchestrator would point the evaluator at the actual checked-out worktree for a given
`agent_run` rather than a fixed path.

## Sandbox note

Real agent-produced code should run this inside the same sandbox the Agent SDK uses for tool
execution (docs/architecture/07-evaluation-framework.md §6) — this reference plugin just runs
the subprocess directly in whatever process hosts it, and does not provide that isolation itself.

## Dev

```
pip install -e ../../sdk/aep-eval-sdk
pip install -e ".[dev]"
pytest tests/
```
