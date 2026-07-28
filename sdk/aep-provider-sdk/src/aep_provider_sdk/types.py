"""Data types exchanged with a ModelProvider (docs/architecture/01-vision-and-principles.md
ADR-002; docs/architecture/04-api-design.md §8)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolDefinition(BaseModel):
    """A tool the model may call during generation — ADR-002's "tool-use" capability is part
    of the generate()/stream() contract, not a separate top-level method, since that's how
    every real provider API models it."""

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """One tool invocation the model has requested."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The result of executing a ToolCall, sent back as a `tool`-role message on the next turn."""

    tool_call_id: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    role: MessageRole
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class FinishReason(str, Enum):
    STOP = "stop"
    MAX_TOKENS = "max_tokens"
    TOOL_USE = "tool_use"
    CONTENT_FILTER = "content_filter"


class GenerationRequest(BaseModel):
    model: str
    messages: list[Message]
    tools: list[ToolDefinition] = Field(default_factory=list)
    max_tokens: int | None = None
    temperature: float | None = None
    stop_sequences: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationResponse(BaseModel):
    model: str
    message: Message
    finish_reason: FinishReason
    usage: TokenUsage
    cost_usd: float | None = None
    raw_provider_response: dict[str, Any] = Field(default_factory=dict)


class GenerationChunkType(str, Enum):
    TEXT_DELTA = "text_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    FINISH = "finish"


class GenerationChunk(BaseModel):
    """One chunk of a streamed generation. `finish_reason`/`usage` are only populated on the
    final `FINISH` chunk."""

    type: GenerationChunkType
    text_delta: str | None = None
    tool_call_delta: ToolCall | None = None
    finish_reason: FinishReason | None = None
    usage: TokenUsage | None = None


class EmbeddingRequest(BaseModel):
    model: str
    inputs: list[str]


class EmbeddingResult(BaseModel):
    embedding: list[float]
    index: int


class EmbeddingResponse(BaseModel):
    model: str
    results: list[EmbeddingResult]
    usage: TokenUsage


class ModelInfo(BaseModel):
    """Backs `GET /providers/{id}/models` (docs/architecture/04-api-design.md §8)."""

    name: str
    supports_tools: bool = False
    supports_streaming: bool = True
    supports_embeddings: bool = False
    max_context_tokens: int | None = None
    input_cost_per_1k_tokens: float | None = None
    output_cost_per_1k_tokens: float | None = None
