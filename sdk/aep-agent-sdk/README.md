# aep-agent-sdk

The `BaseAgent` contract every agent type implements (`plan`/`execute`/`evaluate`/`report`, with
`run`/`cancel`/`retry`/`heartbeat` provided and final). See
`docs/architecture/05-agent-sdk.md`. `backend/` and every agent plugin depend on this package;
this package depends on nothing in `backend/`.

Currently structure-only — `BaseAgent` itself is not yet implemented.
