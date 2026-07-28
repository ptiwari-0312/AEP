# aep-provider-sdk

The plugin boundary between AEP and any LLM provider (ADR-002,
`docs/architecture/01-vision-and-principles.md`). `backend/` and every provider plugin depend on
this package; this package depends on nothing in `backend/`.

Currently structure-only — the provider interface itself is not yet implemented.
