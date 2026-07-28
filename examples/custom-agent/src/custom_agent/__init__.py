"""Reference agent plugin built against aep-agent-sdk (docs/architecture/02-repo-design.md §7)."""

from .config import DocumentationAgentConfig
from .documentation_agent import DocumentationAgent

__all__ = ["DocumentationAgent", "DocumentationAgentConfig"]
