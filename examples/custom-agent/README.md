# custom-agent — DocumentationAgent

A reference agent plugin built against `sdk/aep-agent-sdk` and `sdk/aep-provider-sdk`
(see [docs/architecture/05-agent-sdk.md](../../docs/architecture/05-agent-sdk.md) §13), proving
that a real, LLM-calling agent can be built depending on nothing but those two SDKs — no
`backend/` import anywhere
([docs/architecture/02-repo-design.md](../../docs/architecture/02-repo-design.md) §7).

## What it does

`DocumentationAgent` drafts a documentation update from a task's context (a code diff and/or
existing docs):

- `plan()` — a single step; also carries the task's context content forward via `Plan.notes`,
  since `execute()` only receives the `Plan`, not the original `TaskContext`
- `execute()` — calls an injected `ModelProvider.generate()` with a documentation-writing system
  prompt, checking the `CancellationToken` before and after the call (cooperative cancellation —
  see below)
- `evaluate()` — a cheap self-check, *not* the authoritative quality gate: fails if the content
  is empty/too short, flags lower confidence if the provider's `finish_reason` was `max_tokens`
  (possible truncation)
- `report()` — assembles the `AgentReport`; `run()` fills in status/timing afterward

## Provider is injected, not hardcoded

The constructor takes any `ModelProvider` instance — this agent never imports a specific
provider's SDK (Claude/OpenAI/etc.), per ADR-002. Tests use an in-memory `FakeProvider` (defined
in the test file), so nothing here needs a real API key or network access.

## Cooperative cancellation, demonstrated

`test_cancellation_during_provider_call_produces_cancelled_report` starts `agent.run()` as a
background task, calls `agent.cancel()` while a `SlowProvider` is mid-`await`, and asserts the
run ends `CANCELLED`. The in-flight provider call itself isn't interrupted — cancellation is
only observed at the next checkpoint, right after the call returns, exactly as
docs/architecture/05-agent-sdk.md §7 specifies.

## Config

| Field | Default | Meaning |
|---|---|---|
| `model` | `"default"` | Model name passed to the provider |
| `max_tokens` | `1024` | Forwarded to the generation request |
| `temperature` | `0.3` | Forwarded to the generation request (0.0–2.0) |
| `min_content_length` | `20` | Self-evaluation fails below this many characters |

## Dev

```
pip install -e ../../sdk/aep-agent-sdk -e ../../sdk/aep-provider-sdk
pip install -e ".[dev]"
pytest tests/
```
