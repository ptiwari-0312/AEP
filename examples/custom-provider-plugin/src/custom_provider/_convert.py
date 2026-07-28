"""Converts between AEP's provider-neutral types and the Anthropic Messages API's shapes."""

from __future__ import annotations

import json
from typing import Any

from aep_provider_sdk import (
    FinishReason,
    GenerationResponse,
    Message,
    MessageRole,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

_STOP_REASON_MAP: dict[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "pause_turn": FinishReason.STOP,
    "max_tokens": FinishReason.MAX_TOKENS,
    "model_context_window_exceeded": FinishReason.MAX_TOKENS,
    "tool_use": FinishReason.TOOL_USE,
    "refusal": FinishReason.CONTENT_FILTER,
}


def map_stop_reason(stop_reason: str | None) -> FinishReason:
    if stop_reason is None:
        return FinishReason.STOP
    return _STOP_REASON_MAP.get(stop_reason, FinishReason.STOP)


def to_anthropic_messages(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    """Anthropic has no `system`-role message — it's a separate top-level string — and no
    `tool`-role message — tool results are sent as a `user` message containing `tool_result`
    content blocks. Both are folded in here rather than left for every caller to know."""
    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []

    for message in messages:
        if message.role == MessageRole.SYSTEM:
            if message.content:
                system_parts.append(message.content)
            continue

        if message.role == MessageRole.TOOL:
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_result.tool_call_id,
                            "content": tool_result.content,
                            "is_error": tool_result.is_error,
                        }
                        for tool_result in message.tool_results
                    ],
                }
            )
            continue

        content: list[dict[str, Any]] = []
        if message.content:
            content.append({"type": "text", "text": message.content})
        for tool_call in message.tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.arguments,
                }
            )
        anthropic_messages.append({"role": message.role.value, "content": content})

    system = "\n\n".join(system_parts) if system_parts else None
    return system, anthropic_messages


def to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools
    ]


def from_anthropic_message(response: Any, *, model: str) -> GenerationResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

    return GenerationResponse(
        model=model,
        message=Message(
            role=MessageRole.ASSISTANT,
            content="".join(text_parts) or None,
            tool_calls=tool_calls,
        ),
        finish_reason=map_stop_reason(response.stop_reason),
        usage=TokenUsage(
            input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
        ),
    )


def parse_tool_call_arguments(json_buffer: str) -> dict[str, Any]:
    if not json_buffer:
        return {}
    parsed: dict[str, Any] = json.loads(json_buffer)
    return parsed
