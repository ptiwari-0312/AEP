"""AEP Provider SDK — the plugin interface every LLM provider implements.

See docs/architecture/01-vision-and-principles.md (ADR-002) for the full design rationale.
"""

from .base import ModelProvider
from .errors import (
    ProviderAuthenticationError,
    ProviderContentFilterError,
    ProviderError,
    ProviderModelNotFoundError,
    ProviderRateLimitError,
    ProviderRetryableError,
    ProviderTerminalError,
)
from .retry import ProviderRetryPolicy
from .runtime import EventPublisher, MetricsSink, NullEventPublisher, NullMetricsSink
from .types import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingResult,
    FinishReason,
    GenerationChunk,
    GenerationChunkType,
    GenerationRequest,
    GenerationResponse,
    Message,
    MessageRole,
    ModelInfo,
    TokenUsage,
    ToolCall,
    ToolDefinition,
    ToolResult,
)

__all__ = [
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingResult",
    "EventPublisher",
    "FinishReason",
    "GenerationChunk",
    "GenerationChunkType",
    "GenerationRequest",
    "GenerationResponse",
    "Message",
    "MessageRole",
    "MetricsSink",
    "ModelInfo",
    "ModelProvider",
    "NullEventPublisher",
    "NullMetricsSink",
    "ProviderAuthenticationError",
    "ProviderContentFilterError",
    "ProviderError",
    "ProviderModelNotFoundError",
    "ProviderRateLimitError",
    "ProviderRetryPolicy",
    "ProviderRetryableError",
    "ProviderTerminalError",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
]
