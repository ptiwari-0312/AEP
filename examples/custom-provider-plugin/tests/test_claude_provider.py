from __future__ import annotations

from typing import Any, Self
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from aep_provider_sdk import (
    FinishReason,
    GenerationChunkType,
    GenerationRequest,
    Message,
    MessageRole,
    ProviderAuthenticationError,
    ProviderTerminalError,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from anthropic.types import message as msg_module
from anthropic.types import text_block as text_block_module
from anthropic.types import tool_use_block as tool_use_block_module
from anthropic.types import usage as usage_module
from pydantic import ValidationError

from custom_provider import ClaudeProvider


def _anthropic_message(
    *,
    content: list[Any],
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> msg_module.Message:
    return msg_module.Message(
        id="msg_123",
        content=content,
        model="claude-sonnet-4-5",
        role="assistant",
        type="message",
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=usage_module.Usage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _FakeMessages:
    def __init__(self, create_return: Any = None, create_side_effect: Exception | None = None) -> None:
        self.create = AsyncMock(return_value=create_return, side_effect=create_side_effect)
        self.stream_events: list[Any] = []

    def stream(self, **kwargs: Any) -> _FakeStreamContext:
        return _FakeStreamContext(self.stream_events)


class _FakeStreamContext:
    def __init__(self, events: list[Any]) -> None:
        self._events = events

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    def __aiter__(self) -> Any:
        return self._iter()

    async def _iter(self) -> Any:
        for event in self._events:
            yield event


class _FakeModelsList:
    def __init__(self, models: list[Any]) -> None:
        self._models = models

    def list(self) -> Any:
        return self._aiter()

    async def _aiter(self) -> Any:
        for model in self._models:
            yield model


class _FakeClient:
    def __init__(self, messages: _FakeMessages, models: _FakeModelsList | None = None) -> None:
        self.messages = messages
        self.models = models or _FakeModelsList([])


def _request(**overrides: Any) -> GenerationRequest:
    defaults: dict[str, Any] = {
        "model": "claude-sonnet-4-5",
        "messages": [Message(role=MessageRole.USER, content="hello")],
    }
    defaults.update(overrides)
    return GenerationRequest(**defaults)


async def test_generate_once_returns_text_response_with_cost() -> None:
    anthropic_response = _anthropic_message(
        content=[text_block_module.TextBlock(type="text", text="Hi there!")]
    )
    client = _FakeClient(_FakeMessages(create_return=anthropic_response))
    provider = ClaudeProvider(client=client)

    response = await provider.generate_once(_request())

    assert response.message.content == "Hi there!"
    assert response.finish_reason == FinishReason.STOP
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5


async def test_generate_populates_cost_from_pricing_table() -> None:
    anthropic_response = _anthropic_message(
        content=[text_block_module.TextBlock(type="text", text="Hi!")],
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    client = _FakeClient(_FakeMessages(create_return=anthropic_response))
    provider = ClaudeProvider(client=client)

    response = await provider.generate(_request())

    assert response.cost_usd == pytest.approx(3.0 + 15.0)


async def test_generate_once_maps_tool_use_block_to_tool_call() -> None:
    anthropic_response = _anthropic_message(
        content=[
            tool_use_block_module.ToolUseBlock(
                type="tool_use", id="tool_1", name="get_weather", input={"city": "Paris"}
            )
        ],
        stop_reason="tool_use",
    )
    client = _FakeClient(_FakeMessages(create_return=anthropic_response))
    provider = ClaudeProvider(client=client)

    request = _request(
        tools=[ToolDefinition(name="get_weather", description="Get the weather", input_schema={})]
    )
    response = await provider.generate_once(request)

    assert response.finish_reason == FinishReason.TOOL_USE
    assert len(response.message.tool_calls) == 1
    assert response.message.tool_calls[0].name == "get_weather"
    assert response.message.tool_calls[0].arguments == {"city": "Paris"}


async def test_system_and_tool_result_messages_are_converted_correctly() -> None:
    fake_messages = _FakeMessages(
        create_return=_anthropic_message(content=[text_block_module.TextBlock(type="text", text="ok")])
    )
    client = _FakeClient(fake_messages)
    provider = ClaudeProvider(client=client)

    request = _request(
        messages=[
            Message(role=MessageRole.SYSTEM, content="You are helpful."),
            Message(role=MessageRole.USER, content="What's the weather?"),
            Message(
                role=MessageRole.ASSISTANT,
                tool_calls=[ToolCall(id="tool_1", name="get_weather", arguments={"city": "Paris"})],
            ),
            Message(
                role=MessageRole.TOOL,
                tool_results=[ToolResult(tool_call_id="tool_1", content="Sunny, 22C")],
            ),
        ]
    )
    await provider.generate_once(request)

    sent_kwargs = fake_messages.create.call_args.kwargs
    assert sent_kwargs["system"] == "You are helpful."
    # system message is excluded from the messages list, tool-role becomes a user message
    assert [m["role"] for m in sent_kwargs["messages"]] == ["user", "assistant", "user"]
    assert sent_kwargs["messages"][-1]["content"][0]["type"] == "tool_result"
    assert sent_kwargs["messages"][-1]["content"][0]["tool_use_id"] == "tool_1"


async def test_rate_limit_error_maps_to_retryable_with_retry_after_and_is_retried() -> None:
    request_obj = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response_obj = httpx.Response(status_code=429, headers={"retry-after": "0.01"}, request=request_obj)
    rate_limit_error = anthropic.RateLimitError("slow down", response=response_obj, body=None)

    success_response = _anthropic_message(content=[text_block_module.TextBlock(type="text", text="ok")])
    create_mock = AsyncMock(side_effect=[rate_limit_error, success_response])
    fake_messages = _FakeMessages()
    fake_messages.create = create_mock
    client = _FakeClient(fake_messages)
    provider = ClaudeProvider(client=client)

    response = await provider.generate(_request())

    assert response.message.content == "ok"
    assert create_mock.call_count == 2


async def test_generate_once_maps_authentication_error_as_terminal() -> None:
    request_obj = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    auth_error = anthropic.AuthenticationError(
        "invalid api key", response=httpx.Response(status_code=401, request=request_obj), body=None
    )
    client = _FakeClient(_FakeMessages(create_side_effect=auth_error))
    provider = ClaudeProvider(client=client)

    with pytest.raises(ProviderAuthenticationError):
        await provider.generate_once(_request())


async def test_embed_once_raises_terminal_error_claude_has_no_embeddings_api() -> None:
    provider = ClaudeProvider(client=_FakeClient(_FakeMessages()))

    with pytest.raises(ProviderTerminalError, match="no embeddings API"):
        await provider.embed_once(request=None)  # type: ignore[arg-type]


async def test_stream_once_yields_text_deltas_then_finish_with_usage() -> None:
    from anthropic.types.message_delta_usage import MessageDeltaUsage
    from anthropic.types.raw_content_block_delta_event import RawContentBlockDeltaEvent
    from anthropic.types.raw_content_block_start_event import RawContentBlockStartEvent
    from anthropic.types.raw_content_block_stop_event import RawContentBlockStopEvent
    from anthropic.types.raw_message_delta_event import Delta, RawMessageDeltaEvent
    from anthropic.types.raw_message_start_event import RawMessageStartEvent
    from anthropic.types.raw_message_stop_event import RawMessageStopEvent
    from anthropic.types.text_delta import TextDelta

    events = [
        RawMessageStartEvent(
            type="message_start",
            message=_anthropic_message(content=[], input_tokens=7, output_tokens=0),
        ),
        RawContentBlockStartEvent(
            type="content_block_start",
            index=0,
            content_block=text_block_module.TextBlock(type="text", text=""),
        ),
        RawContentBlockDeltaEvent(
            type="content_block_delta", index=0, delta=TextDelta(type="text_delta", text="Hel")
        ),
        RawContentBlockDeltaEvent(
            type="content_block_delta", index=0, delta=TextDelta(type="text_delta", text="lo")
        ),
        RawContentBlockStopEvent(type="content_block_stop", index=0),
        RawMessageDeltaEvent(
            type="message_delta",
            delta=Delta(stop_reason="end_turn"),
            usage=MessageDeltaUsage(output_tokens=3),
        ),
        RawMessageStopEvent(type="message_stop"),
    ]
    fake_messages = _FakeMessages()
    fake_messages.stream_events = events
    provider = ClaudeProvider(client=_FakeClient(fake_messages))

    chunks = [chunk async for chunk in provider.stream(_request())]

    assert [c.type for c in chunks] == [
        GenerationChunkType.TEXT_DELTA,
        GenerationChunkType.TEXT_DELTA,
        GenerationChunkType.FINISH,
    ]
    assert "".join(c.text_delta for c in chunks[:2]) == "Hello"
    assert chunks[-1].finish_reason == FinishReason.STOP
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.input_tokens == 7
    assert chunks[-1].usage.output_tokens == 3


async def test_stream_once_yields_tool_call_delta_after_content_block_stop() -> None:
    from anthropic.types.input_json_delta import InputJSONDelta
    from anthropic.types.message_delta_usage import MessageDeltaUsage
    from anthropic.types.raw_content_block_delta_event import RawContentBlockDeltaEvent
    from anthropic.types.raw_content_block_start_event import RawContentBlockStartEvent
    from anthropic.types.raw_content_block_stop_event import RawContentBlockStopEvent
    from anthropic.types.raw_message_delta_event import Delta, RawMessageDeltaEvent
    from anthropic.types.raw_message_start_event import RawMessageStartEvent
    from anthropic.types.raw_message_stop_event import RawMessageStopEvent

    events = [
        RawMessageStartEvent(
            type="message_start", message=_anthropic_message(content=[], input_tokens=4, output_tokens=0)
        ),
        RawContentBlockStartEvent(
            type="content_block_start",
            index=0,
            content_block=tool_use_block_module.ToolUseBlock(
                type="tool_use", id="tool_1", name="get_weather", input={}
            ),
        ),
        RawContentBlockDeltaEvent(
            type="content_block_delta",
            index=0,
            delta=InputJSONDelta(type="input_json_delta", partial_json='{"city": '),
        ),
        RawContentBlockDeltaEvent(
            type="content_block_delta",
            index=0,
            delta=InputJSONDelta(type="input_json_delta", partial_json='"Paris"}'),
        ),
        RawContentBlockStopEvent(type="content_block_stop", index=0),
        RawMessageDeltaEvent(
            type="message_delta",
            delta=Delta(stop_reason="tool_use"),
            usage=MessageDeltaUsage(output_tokens=6),
        ),
        RawMessageStopEvent(type="message_stop"),
    ]
    fake_messages = _FakeMessages()
    fake_messages.stream_events = events
    provider = ClaudeProvider(client=_FakeClient(fake_messages))

    chunks = [chunk async for chunk in provider.stream(_request())]

    tool_chunk = next(c for c in chunks if c.type == GenerationChunkType.TOOL_CALL_DELTA)
    assert tool_chunk.tool_call_delta is not None
    assert tool_chunk.tool_call_delta.name == "get_weather"
    assert tool_chunk.tool_call_delta.arguments == {"city": "Paris"}
    assert chunks[-1].finish_reason == FinishReason.TOOL_USE


def test_count_tokens_is_a_documented_approximation() -> None:
    provider = ClaudeProvider(client=_FakeClient(_FakeMessages()))

    assert provider.count_tokens(model="claude-sonnet-4-5", text="a" * 40) == 10


async def test_list_models_maps_anthropic_model_info() -> None:
    from anthropic.types import model_info as model_info_module

    anthropic_models = [
        model_info_module.ModelInfo(
            id="claude-sonnet-4-5",
            created_at="2025-01-01T00:00:00Z",
            display_name="Claude Sonnet 4.5",
            type="model",
        )
    ]
    client = _FakeClient(_FakeMessages(), models=_FakeModelsList(anthropic_models))
    provider = ClaudeProvider(client=client)

    models = await provider.list_models()

    assert len(models) == 1
    assert models[0].name == "claude-sonnet-4-5"
    assert models[0].supports_embeddings is False


def test_invalid_config_raises_at_construction() -> None:
    with pytest.raises(ValidationError):
        ClaudeProvider(client=_FakeClient(_FakeMessages()), config={"default_max_tokens": -1})
