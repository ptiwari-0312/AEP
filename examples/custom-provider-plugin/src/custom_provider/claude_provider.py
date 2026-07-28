"""ClaudeProvider: a ModelProvider implementation wrapping the official Anthropic Python SDK.

Reference implementation built against sdk/aep-provider-sdk, for ADR-002
(docs/architecture/01-vision-and-principles.md) — this is the only module in this example
package allowed to import `anthropic` directly; everything upstream of it talks to the
provider-neutral `ModelProvider` interface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import anthropic
from aep_provider_sdk import (
    EmbeddingRequest,
    EmbeddingResponse,
    GenerationChunk,
    GenerationChunkType,
    GenerationRequest,
    GenerationResponse,
    Message,
    ModelInfo,
    ModelProvider,
    ProviderTerminalError,
    TokenUsage,
    ToolCall,
)

from ._convert import (
    from_anthropic_message,
    map_stop_reason,
    parse_tool_call_arguments,
    to_anthropic_messages,
    to_anthropic_tools,
)
from ._errors import map_anthropic_error
from .config import ClaudeProviderConfig, ModelPricing


class ClaudeProvider(ModelProvider):
    provider_name = "claude"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: anthropic.AsyncAnthropic | None = None,
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(config=config, **kwargs)
        self._settings = ClaudeProviderConfig.model_validate(self.config)
        # max_retries=0: our own generate()/stream()/embed() wrappers already retry transient
        # failures (ModelProvider's ProviderRetryPolicy) — leaving the Anthropic client's own
        # built-in retry on top would double the effective backoff for no benefit.
        self._client = client or anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        kwargs = self._build_request_kwargs(request)
        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.AnthropicError as exc:
            raise map_anthropic_error(exc) from exc

        generated = from_anthropic_message(response, model=request.model)
        cost = self.estimate_cost(model=request.model, usage=generated.usage)
        return generated.model_copy(update={"cost_usd": cost})

    async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        kwargs = self._build_request_kwargs(request)
        input_tokens = 0
        output_tokens = 0
        finish_reason = None
        pending_tool_call: dict[str, str] | None = None

        try:
            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "message_start":
                        input_tokens = event.message.usage.input_tokens
                    elif event.type == "content_block_start":
                        if event.content_block.type == "tool_use":
                            pending_tool_call = {
                                "id": event.content_block.id,
                                "name": event.content_block.name,
                                "json_buffer": "",
                            }
                    elif event.type == "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield GenerationChunk(
                                type=GenerationChunkType.TEXT_DELTA, text_delta=event.delta.text
                            )
                        elif event.delta.type == "input_json_delta" and pending_tool_call is not None:
                            pending_tool_call["json_buffer"] += event.delta.partial_json
                    elif event.type == "content_block_stop":
                        if pending_tool_call is not None:
                            yield GenerationChunk(
                                type=GenerationChunkType.TOOL_CALL_DELTA,
                                tool_call_delta=ToolCall(
                                    id=pending_tool_call["id"],
                                    name=pending_tool_call["name"],
                                    arguments=parse_tool_call_arguments(pending_tool_call["json_buffer"]),
                                ),
                            )
                            pending_tool_call = None
                    elif event.type == "message_delta":
                        output_tokens = event.usage.output_tokens
                        finish_reason = map_stop_reason(event.delta.stop_reason)
        except anthropic.AnthropicError as exc:
            raise map_anthropic_error(exc) from exc

        yield GenerationChunk(
            type=GenerationChunkType.FINISH,
            finish_reason=finish_reason or map_stop_reason(None),
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        )

    async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise ProviderTerminalError(
            "Claude has no embeddings API — use a dedicated embedding provider "
            "(e.g. Vertex AI or OpenAI) for the embed() capability."
        )

    def count_tokens(
        self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
    ) -> int:
        # Approximate only. Anthropic's exact token count (client.messages.count_tokens) is an
        # async API call, but ModelProvider.count_tokens() is declared synchronous (aimed at
        # providers with a local tokenizer) — so this falls back to Anthropic's own documented
        # ~4-characters-per-token rule of thumb rather than an exact count. See the plugin
        # README for why this is a real SDK interface gap, not an oversight.
        if text is not None:
            return max(1, len(text) // 4)
        if messages:
            total_chars = sum(len(m.content or "") for m in messages)
            return max(1, total_chars // 4)
        return 0

    async def list_models(self) -> list[ModelInfo]:
        try:
            models = [model async for model in self._client.models.list()]
        except anthropic.AnthropicError as exc:
            raise map_anthropic_error(exc) from exc
        return [
            ModelInfo(
                name=model.id,
                supports_tools=True,
                supports_streaming=True,
                supports_embeddings=False,
                max_context_tokens=getattr(model, "max_input_tokens", None),
            )
            for model in models
        ]

    def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
        pricing = self._resolve_pricing(model)
        if pricing is None:
            return 0.0
        return (
            usage.input_tokens / 1_000_000 * pricing.input_cost_per_million_tokens
            + usage.output_tokens / 1_000_000 * pricing.output_cost_per_million_tokens
        )

    def _resolve_pricing(self, model: str) -> ModelPricing | None:
        for key, pricing in self._settings.pricing.items():
            if key in model:
                return pricing
        return None

    def _build_request_kwargs(self, request: GenerationRequest) -> dict[str, Any]:
        system, messages = to_anthropic_messages(request.messages)
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or self._settings.default_max_tokens,
        }
        if system:
            kwargs["system"] = system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences
        if request.tools:
            kwargs["tools"] = to_anthropic_tools(request.tools)
        return kwargs
