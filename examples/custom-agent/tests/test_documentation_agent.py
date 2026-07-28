from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

import pytest
from aep_agent_sdk import AgentRunStatus, TaskContext
from aep_provider_sdk import (
    EmbeddingRequest,
    EmbeddingResponse,
    FinishReason,
    GenerationChunk,
    GenerationRequest,
    GenerationResponse,
    Message,
    MessageRole,
    ModelInfo,
    ModelProvider,
    TokenUsage,
)
from pydantic import ValidationError

from custom_agent import DocumentationAgent


class FakeProvider(ModelProvider):
    provider_name = "fake"

    def __init__(
        self,
        *,
        response_text: str = "## Overview\nThis documents the new feature in detail.",
        finish_reason: FinishReason = FinishReason.STOP,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._response_text = response_text
        self._finish_reason = finish_reason
        self.requests: list[GenerationRequest] = []

    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        return GenerationResponse(
            model=request.model,
            message=Message(role=MessageRole.ASSISTANT, content=self._response_text),
            finish_reason=self._finish_reason,
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            cost_usd=0.002,
        )

    async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        raise NotImplementedError
        yield  # pragma: no cover - keeps this an async generator

    async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise NotImplementedError

    def count_tokens(
        self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
    ) -> int:
        return 0

    async def list_models(self) -> list[ModelInfo]:
        return []

    def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
        return 0.0


class SlowProvider(FakeProvider):
    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        await asyncio.sleep(0.2)
        return await super().generate_once(request)


def _context(content: str = "diff: added a foo() helper function") -> TaskContext:
    return TaskContext(task_id=uuid4(), content=content)


async def test_execute_calls_provider_and_returns_documentation_artifact() -> None:
    provider = FakeProvider()
    agent = DocumentationAgent(provider=provider, agent_id=uuid4(), version="0.1.0")

    report = await agent.run(_context())

    assert report.agent_run_status == AgentRunStatus.COMPLETED
    assert report.execution_result is not None
    assert report.execution_result.artifacts[0].content.startswith("## Overview")
    assert report.self_evaluation is not None
    assert report.self_evaluation.passed is True
    assert len(provider.requests) == 1
    assert provider.requests[0].messages[-1].content == "diff: added a foo() helper function"


async def test_self_evaluation_fails_when_content_too_short() -> None:
    provider = FakeProvider(response_text="ok")
    agent = DocumentationAgent(
        provider=provider, agent_id=uuid4(), version="0.1.0", config={"min_content_length": 50}
    )

    report = await agent.run(_context())

    assert report.self_evaluation is not None
    assert report.self_evaluation.passed is False


async def test_self_evaluation_flags_lower_confidence_when_truncated() -> None:
    provider = FakeProvider(response_text="A" * 100, finish_reason=FinishReason.MAX_TOKENS)
    agent = DocumentationAgent(provider=provider, agent_id=uuid4(), version="0.1.0")

    report = await agent.run(_context())

    assert report.self_evaluation is not None
    assert report.self_evaluation.passed is True
    assert report.self_evaluation.confidence < 0.9


async def test_cancellation_during_provider_call_produces_cancelled_report() -> None:
    provider = SlowProvider()
    agent = DocumentationAgent(provider=provider, agent_id=uuid4(), version="0.1.0")

    run_task = asyncio.create_task(agent.run(_context()))
    await asyncio.sleep(0.05)
    await agent.cancel()
    report = await run_task

    assert report.agent_run_status == AgentRunStatus.CANCELLED


def test_invalid_config_raises_at_construction() -> None:
    with pytest.raises(ValidationError):
        DocumentationAgent(provider=FakeProvider(), agent_id=uuid4(), version="0.1.0", config={"temperature": 5.0})
