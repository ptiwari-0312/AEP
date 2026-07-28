from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest

from aep_provider_sdk import (
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
    ModelProvider,
    ProviderRateLimitError,
    ProviderRetryableError,
    ProviderRetryPolicy,
    ProviderTerminalError,
    TokenUsage,
)


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))

    def event_types(self) -> list[str]:
        return [event_type for event_type, _ in self.events]


class RecordingMetricsSink:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict[str, Any]]] = []

    def emit(self, metric_name: str, value: float, **tags: Any) -> None:
        self.metrics.append((metric_name, value, tags))


class FakeProvider(ModelProvider):
    provider_name = "fake"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.generate_calls = 0

    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        self.generate_calls += 1
        return GenerationResponse(
            model=request.model,
            message=Message(role=MessageRole.ASSISTANT, content="hello"),
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(input_tokens=5, output_tokens=3),
            cost_usd=0.001,
        )

    async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        yield GenerationChunk(type=GenerationChunkType.TEXT_DELTA, text_delta="hel")
        yield GenerationChunk(type=GenerationChunkType.TEXT_DELTA, text_delta="lo")
        yield GenerationChunk(
            type=GenerationChunkType.FINISH,
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(input_tokens=5, output_tokens=2),
        )

    async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            model=request.model,
            results=[EmbeddingResult(embedding=[0.1, 0.2], index=i) for i in range(len(request.inputs))],
            usage=TokenUsage(input_tokens=len(request.inputs) * 2, output_tokens=0),
        )

    def count_tokens(
        self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
    ) -> int:
        return 42

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(name="fake-model-1")]

    def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
        return usage.total_tokens * 0.0001


class FlakyThenSucceedsProvider(ModelProvider):
    provider_name = "flaky"

    def __init__(self, *, failures_before_success: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._remaining_failures = failures_before_success

    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise ProviderRetryableError("transient timeout")
        return GenerationResponse(
            model=request.model,
            message=Message(role=MessageRole.ASSISTANT, content="ok"),
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )

    async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise ProviderRetryableError("transient timeout")
            yield  # pragma: no cover - makes this an async generator
        yield GenerationChunk(
            type=GenerationChunkType.FINISH,
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
        )

    async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise AssertionError("not used in this test")

    def count_tokens(
        self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
    ) -> int:
        return 1

    async def list_models(self) -> list[ModelInfo]:
        return []

    def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
        return 0.0


class MidStreamFailureProvider(ModelProvider):
    provider_name = "midstream"

    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        raise AssertionError("not used in this test")

    async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        yield GenerationChunk(type=GenerationChunkType.TEXT_DELTA, text_delta="partial")
        raise ProviderRetryableError("connection dropped mid-stream")

    async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise AssertionError("not used in this test")

    def count_tokens(
        self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
    ) -> int:
        return 0

    async def list_models(self) -> list[ModelInfo]:
        return []

    def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
        return 0.0


class AlwaysTerminalProvider(ModelProvider):
    provider_name = "terminal"

    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        raise ProviderTerminalError("invalid api key")

    async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        raise ProviderTerminalError("invalid api key")
        yield  # pragma: no cover

    async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        raise AssertionError("not used in this test")

    def count_tokens(
        self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
    ) -> int:
        return 0

    async def list_models(self) -> list[ModelInfo]:
        return []

    def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
        return 0.0


def _request() -> GenerationRequest:
    return GenerationRequest(model="fake-model-1", messages=[Message(role=MessageRole.USER, content="hi")])


async def test_generate_happy_path_emits_metrics_and_events() -> None:
    publisher = RecordingEventPublisher()
    metrics = RecordingMetricsSink()
    provider = FakeProvider(event_publisher=publisher, metrics_sink=metrics)

    response = await provider.generate(_request())

    assert response.message.content == "hello"
    assert response.usage.total_tokens == 8
    assert publisher.event_types() == ["provider.generate.attempting", "provider.generate.succeeded"]
    metric_names = {name for name, _, _ in metrics.metrics}
    assert "provider.input_tokens" in metric_names
    assert "provider.output_tokens" in metric_names
    assert "provider.cost_usd" in metric_names


async def test_stream_happy_path_yields_all_chunks_in_order() -> None:
    provider = FakeProvider()
    chunks = [chunk async for chunk in provider.stream(_request())]

    assert [c.type for c in chunks] == [
        GenerationChunkType.TEXT_DELTA,
        GenerationChunkType.TEXT_DELTA,
        GenerationChunkType.FINISH,
    ]
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.output_tokens == 2


async def test_embed_happy_path() -> None:
    provider = FakeProvider()
    response = await provider.embed(EmbeddingRequest(model="fake-model-1", inputs=["a", "b"]))

    assert len(response.results) == 2
    assert response.usage.input_tokens == 4


async def test_generate_retries_transient_error_then_succeeds() -> None:
    publisher = RecordingEventPublisher()
    provider = FlakyThenSucceedsProvider(
        failures_before_success=2,
        event_publisher=publisher,
        retry_policy=ProviderRetryPolicy(max_attempts=5, backoff_base_seconds=0.01, backoff_multiplier=1.0),
    )

    response = await provider.generate(_request())

    assert response.message.content == "ok"
    assert provider._remaining_failures == 0
    assert publisher.event_types().count("provider.generate.attempting") == 3
    assert publisher.event_types().count("provider.generate.succeeded") == 1


async def test_generate_terminal_error_is_not_retried() -> None:
    publisher = RecordingEventPublisher()
    provider = AlwaysTerminalProvider(
        event_publisher=publisher,
        retry_policy=ProviderRetryPolicy(max_attempts=5, backoff_base_seconds=0.01),
    )

    with pytest.raises(ProviderTerminalError):
        await provider.generate(_request())

    assert publisher.event_types() == ["provider.generate.attempting", "provider.generate.failed"]


async def test_rate_limit_retry_after_is_honored_over_backoff_schedule() -> None:
    provider = FlakyThenSucceedsProvider(
        failures_before_success=0,
        retry_policy=ProviderRetryPolicy(backoff_base_seconds=999.0),
    )
    error = ProviderRateLimitError("slow down", retry_after_seconds=0.01)
    backoff = provider._retry_policy.backoff_seconds(1, retry_after_seconds=error.retry_after_seconds)

    assert backoff == 0.01


async def test_stream_retries_before_first_chunk() -> None:
    publisher = RecordingEventPublisher()
    provider = FlakyThenSucceedsProvider(
        failures_before_success=1,
        event_publisher=publisher,
        retry_policy=ProviderRetryPolicy(max_attempts=5, backoff_base_seconds=0.01, backoff_multiplier=1.0),
    )

    chunks = [chunk async for chunk in provider.stream(_request())]

    assert len(chunks) == 1
    assert chunks[0].type == GenerationChunkType.FINISH
    assert publisher.event_types().count("provider.stream.attempting") == 2


async def test_stream_does_not_retry_after_first_chunk_yielded() -> None:
    provider = MidStreamFailureProvider()

    with pytest.raises(ProviderRetryableError, match="dropped mid-stream"):
        _ = [chunk async for chunk in provider.stream(_request())]


def test_subclass_cannot_override_final_lifecycle_methods() -> None:
    with pytest.raises(TypeError, match="generate"):

        class BadProvider(ModelProvider):
            provider_name = "bad"

            async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
                raise AssertionError("unused")

            async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
                raise AssertionError("unused")
                yield  # pragma: no cover

            async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
                raise AssertionError("unused")

            def count_tokens(
                self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
            ) -> int:
                return 0

            async def list_models(self) -> list[ModelInfo]:
                return []

            def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
                return 0.0

            async def generate(self, request: GenerationRequest) -> GenerationResponse:  # type: ignore[override]
                raise AssertionError("must never be called")


def test_provider_without_provider_name_raises_at_construction() -> None:
    class NoNameProvider(ModelProvider):
        async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
            raise AssertionError("unused")

        async def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
            raise AssertionError("unused")
            yield  # pragma: no cover

        async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
            raise AssertionError("unused")

        def count_tokens(
            self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
        ) -> int:
            return 0

        async def list_models(self) -> list[ModelInfo]:
            return []

        def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
            return 0.0

    with pytest.raises(TypeError, match="provider_name"):
        NoNameProvider()
