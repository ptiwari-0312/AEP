"""Reference provider plugin wrapping the official Anthropic SDK, built against aep-provider-sdk
(docs/architecture/02-repo-design.md §7)."""

from .claude_provider import ClaudeProvider
from .config import ClaudeProviderConfig, ModelPricing

__all__ = ["ClaudeProvider", "ClaudeProviderConfig", "ModelPricing"]
