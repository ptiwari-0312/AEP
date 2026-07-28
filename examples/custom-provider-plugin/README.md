# custom-provider-plugin — ClaudeProvider

A reference provider plugin wrapping the official Anthropic Python SDK, built against
`sdk/aep-provider-sdk` (see [docs/architecture/01-vision-and-principles.md](../../docs/architecture/01-vision-and-principles.md)
ADR-002). `anthropic` is imported only inside this package — everything else in AEP talks to
the provider-neutral `ModelProvider` interface, never to a vendor SDK directly.

## What it does

- **`generate`/`stream`** — converts AEP's provider-neutral `Message`/`ToolDefinition` types to
  and from the Anthropic Messages API's shapes (`_convert.py`), including the two things that
  don't map 1:1: Anthropic has no `system`-role message (it's a separate top-level string) and
  no `tool`-role message (tool results are sent as a `user` message with `tool_result` content
  blocks) — both handled in `to_anthropic_messages()`.
- **Error mapping** (`_errors.py`) — maps `anthropic.RateLimitError` (with its `retry-after`
  header) / `AuthenticationError` / `NotFoundError` / connection & server errors onto AEP's
  `ProviderRateLimitError` / `ProviderAuthenticationError` / `ProviderModelNotFoundError` /
  `ProviderRetryableError` hierarchy, so `ModelProvider.generate()`'s built-in retry logic
  (in the base SDK) actually engages correctly.
- **`embed`** — Claude has no embeddings API. `embed_once()` raises `ProviderTerminalError`
  with a clear message rather than pretending to support it.
- **`list_models`** — calls `client.models.list()`.
- **`estimate_cost`** — a small illustrative pricing table (`config.py`) keyed by model-name
  substring (`opus`/`sonnet`/`haiku`). **This is example data, not a live pricing feed** — verify
  against <https://www.anthropic.com/pricing> before relying on it for anything real.

## A real SDK-interface gap, found while building this

`ModelProvider.count_tokens()` is declared **synchronous** (aimed at providers with a local
tokenizer, e.g. `tiktoken`). Anthropic's actual exact token count
(`client.messages.count_tokens()`) is an **async API call** — there's no local Claude tokenizer
to call synchronously. This plugin's `count_tokens()` falls back to Anthropic's own documented
~4-characters-per-token rule of thumb, clearly marked as an approximation, not the exact count
the base interface's docstring promises.

This is a genuine mismatch between the SDK contract and this provider's reality, not a bug in
this plugin. Fixing it properly means either accepting the approximation for Claude specifically,
or evolving `ModelProvider.count_tokens()` to be async across all three provider types — a
breaking SDK change that (per `docs/architecture/09-engineering-standards.md` §11) would need
every existing provider plugin and its example updated in the same PR. Left as-is here,
flagged rather than silently patched.

## Testing without an API key

The constructor accepts an injected `client: anthropic.AsyncAnthropic | None`. Tests supply a
fake client exposing fake `messages.create`/`messages.stream`/`models.list`, built from **real**
`anthropic.types` objects (`Message`, `TextBlock`, `ToolUseBlock`, the `Raw*Event` streaming
types) rather than hand-rolled shapes — so the conversion code is verified against the actual
SDK's data, not against guesses about it. No network access or `ANTHROPIC_API_KEY` needed to run
`pytest tests/`.

## Retry note

The Anthropic client is constructed with `max_retries=0`. `ModelProvider`'s own
`generate()`/`stream()`/`embed()` wrappers already retry transient failures via
`ProviderRetryPolicy` — leaving the Anthropic client's own built-in retry on top would double
the effective backoff for no benefit.

## Dev

```
pip install -e ../../sdk/aep-provider-sdk
pip install -e ".[dev]"
pytest tests/
```
