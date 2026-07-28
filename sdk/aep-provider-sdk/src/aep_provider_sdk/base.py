"""The ModelProvider contract (docs/architecture/01-vision-and-principles.md ADR-002)."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, ClassVar, final

from .retry import ProviderRetryPolicy
from .runtime import EventPublisher, MetricsSink, NullEventPublisher, NullMetricsSink
from .types import (
    EmbeddingRequest,
    EmbeddingResponse,
    GenerationChunk,
    GenerationChunkType,
    GenerationRequest,
    GenerationResponse,
    Message,
    ModelInfo,
    TokenUsage,
)

_FINAL_METHOD_NAMES = ("generate", "stream", "embed")


class ModelProvider(ABC):
    """Every LLM provider (Claude, OpenAI, Gemini, Vertex AI, or a future one) subclasses this
    and implements exactly the hook methods below. No module outside `providers/` may ever
    import a specific provider's SDK directly — everything else in AEP talks only to this
    interface (ADR-002). `generate`, `stream`, and `embed` are final: they add retry-on-
    transient-failure, logging, and metrics uniformly, so a provider outage or rate limit never
    requires touching orchestration or agent code — which is the entire point of ADR-002.
    """

    provider_name: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for method_name in _FINAL_METHOD_NAMES:
            if getattr(cls, method_name) is not getattr(ModelProvider, method_name):
                raise TypeError(
                    f"{cls.__name__} may not override ModelProvider.{method_name}() — it is "
                    f"final by design; implement {method_name}_once() instead "
                    f"(docs/architecture/01-vision-and-principles.md ADR-002)."
                )

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        event_publisher: EventPublisher | None = None,
        metrics_sink: MetricsSink | None = None,
        retry_policy: ProviderRetryPolicy | None = None,
    ) -> None:
        if not hasattr(self, "provider_name"):
            raise TypeError(f"{type(self).__name__} must set a class-level provider_name")
        self.config: dict[str, Any] = config or {}
        self.log = logging.getLogger(f"aep.provider.{self.provider_name}")
        self._event_publisher: EventPublisher = event_publisher or NullEventPublisher()
        self._metrics_sink: MetricsSink = metrics_sink or NullMetricsSink()
        self._retry_policy = retry_policy or ProviderRetryPolicy()

    # ---- hook methods: implemented by concrete provider plugins ----------------------------

    @abstractmethod
    async def generate_once(self, request: GenerationRequest) -> GenerationResponse:
        """A single generation attempt — no retry logic here, that's generate()'s job."""

    @abstractmethod
    def stream_once(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        """A single streaming attempt."""

    @abstractmethod
    async def embed_once(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """A single embedding attempt."""

    @abstractmethod
    def count_tokens(
        self, *, model: str, messages: Sequence[Message] | None = None, text: str | None = None
    ) -> int:
        """Exact token count using this provider's own tokenizer — what the Context Builder
        calls to re-count an assembled package against the model actually selected for a run
        (docs/architecture/06-context-builder.md §8)."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Backs `GET /providers/{id}/models` (docs/architecture/04-api-design.md §8)."""

    @abstractmethod
    def estimate_cost(self, *, model: str, usage: TokenUsage) -> float:
        """USD cost for the given token usage on this model."""

    # ---- lifecycle methods: final, not overridable ----------------------------------------

    @final
    def emit_metric(self, metric_name: str, value: float, **tags: Any) -> None:
        self._metrics_sink.emit(metric_name, value, provider=self.provider_name, **tags)

    @final
    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Retries generate_once() on a retryable error, honoring
        `ProviderRateLimitError.retry_after_seconds` when present; logs and emits standard
        metrics around every attempt."""
        attempt = 1
        while True:
            try:
                await self._publish(
                    "provider.generate.attempting", {"model": request.model, "attempt": attempt}
                )
                response = await self.generate_once(request)
                self._emit_generation_metrics(response)
                await self._publish(
                    "provider.generate.succeeded", {"model": request.model, "attempt": attempt}
                )
                return response
            except Exception as exc:
                # either retry or propagate, per the exception-handling standard
                # (docs/architecture/09-engineering-standards.md §6).
                if not self._should_retry(exc, attempt):
                    await self._publish(
                        "provider.generate.failed",
                        {"model": request.model, "attempt": attempt, "error": str(exc)},
                    )
                    raise
                await self._sleep_before_retry(exc, attempt)
                attempt += 1

    @final
    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        """Retries only connection setup — once the first chunk has been yielded, a failure
        propagates rather than silently restarting a partially-consumed stream, since the
        caller may have already forwarded earlier chunks onward (e.g. over the Agent
        Orchestrator's SSE endpoint, docs/architecture/04-api-design.md §5.6)."""
        attempt = 1
        while True:
            try:
                await self._publish(
                    "provider.stream.attempting", {"model": request.model, "attempt": attempt}
                )
                chunk_iterator = self.stream_once(request)
                first_chunk = await chunk_iterator.__anext__()
            except StopAsyncIteration:
                return
            except Exception as exc:
                if not self._should_retry(exc, attempt):
                    await self._publish(
                        "provider.stream.failed",
                        {"model": request.model, "attempt": attempt, "error": str(exc)},
                    )
                    raise
                await self._sleep_before_retry(exc, attempt)
                attempt += 1
                continue

            yield first_chunk
            if first_chunk.type == GenerationChunkType.FINISH:
                await self._publish(
                    "provider.stream.succeeded", {"model": request.model, "attempt": attempt}
                )
                return

            async for chunk in chunk_iterator:
                yield chunk
                if chunk.type == GenerationChunkType.FINISH:
                    if chunk.usage is not None:
                        self.emit_metric(
                            "provider.output_tokens",
                            float(chunk.usage.output_tokens),
                            model=request.model,
                        )
                    await self._publish(
                        "provider.stream.succeeded",
                        {"model": request.model, "attempt": attempt},
                    )
            return

    @final
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        attempt = 1
        while True:
            try:
                await self._publish(
                    "provider.embed.attempting", {"model": request.model, "attempt": attempt}
                )
                response = await self.embed_once(request)
                self.emit_metric(
                    "provider.embed.input_tokens",
                    float(response.usage.input_tokens),
                    model=request.model,
                )
                await self._publish(
                    "provider.embed.succeeded", {"model": request.model, "attempt": attempt}
                )
                return response
            except Exception as exc:
                if not self._should_retry(exc, attempt):
                    await self._publish(
                        "provider.embed.failed",
                        {"model": request.model, "attempt": attempt, "error": str(exc)},
                    )
                    raise
                await self._sleep_before_retry(exc, attempt)
                attempt += 1

    # ---- internal helpers -------------------------------------------------------------------

    def _should_retry(self, exc: Exception, attempt: int) -> bool:
        return self._retry_policy.is_retryable(exc) and attempt < self._retry_policy.max_attempts

    async def _sleep_before_retry(self, exc: Exception, attempt: int) -> None:
        retry_after = getattr(exc, "retry_after_seconds", None)
        backoff = self._retry_policy.backoff_seconds(attempt, retry_after_seconds=retry_after)
        self.log.warning(
            "provider call retrying: provider=%s attempt=%s error=%s backoff=%.1fs",
            self.provider_name,
            attempt,
            exc,
            backoff,
        )
        await asyncio.sleep(backoff)

    async def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        envelope: dict[str, Any] = {"provider": self.provider_name, **payload}
        await self._event_publisher.publish(event_type, envelope)

    def _emit_generation_metrics(self, response: GenerationResponse) -> None:
        tags = {"model": response.model}
        self.emit_metric("provider.input_tokens", float(response.usage.input_tokens), **tags)
        self.emit_metric("provider.output_tokens", float(response.usage.output_tokens), **tags)
        if response.cost_usd is not None:
            self.emit_metric("provider.cost_usd", response.cost_usd, **tags)
