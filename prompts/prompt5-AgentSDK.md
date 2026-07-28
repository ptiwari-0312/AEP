Design an extensible Agent SDK.

Every agent must implement a common interface.

Example agent types:

PlannerAgent

ArchitectAgent

CodingAgent

TestingAgent

ReviewAgent

DocumentationAgent

SecurityAgent

EvaluationAgent

Every agent should expose:

plan()

execute()

evaluate()

report()

cancel()

retry()

heartbeat()

Support asynchronous execution.

Support retries.

Support event publishing.

Support logging.

Support metrics.

Explain all design decisions.

Generate architecture only.