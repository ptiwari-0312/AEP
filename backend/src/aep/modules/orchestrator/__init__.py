"""Agent Orchestrator — assigns agents to tasks, drives their lifecycle
(plan -> execute -> evaluate -> report), and enforces the human-approval gate before merge.
See `docs/architecture/05-agent-sdk.md` and `docs/architecture/04-api-design.md` §5.

This is the module's public surface (docs/architecture/02-repo-design.md §2): its FastAPI
`router` (for `main.py` to mount) and its `AgentRunService`/`AgentService`/`TaskReviewService`
(for another module to call into, the same way this module calls into `task_memory`'s
`TaskService`, `context_builder`'s `ContextBuilderService`, and `auth`'s `AuditService`).
"""

from .api import router
from .services import AgentRunService, AgentService, TaskReviewService

__all__ = ["AgentRunService", "AgentService", "TaskReviewService", "router"]
