"""Backend-only OpenAI Chat Completions adapter with bounded retries and SSE."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from decimal import Decimal
from typing import Any, TypeVar, overload

import httpx
from pydantic import BaseModel, ValidationError

from aiseoonline_api.ai_core.contracts import (
    BudgetExceeded,
    CredentialsUnavailable,
    GenerationRequest,
    InvalidModelOutput,
    LLMTimeout,
    ModelPricing,
    ModelResult,
    ProviderRateLimited,
    ProviderUnavailable,
    StreamEvent,
    TokenBudget,
    TokenUsage,
)
from aiseoonline_api.ai_core.prompts import template_for
from aiseoonline_api.config import Settings
from aiseoonline_api.observability import span

logger = logging.getLogger("aiseoonline.ai")
T = TypeVar("T", bound=BaseModel)
_RETRYABLE = {429, 500, 502, 503, 504}
_SSE_END = "[DONE]"


class OpenAIChatProvider:
    """Network client is injectable, so every automated test uses an in-memory transport."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        budget: TokenBudget,
        pricing: ModelPricing | None = None,
        http_client: httpx.AsyncClient | None = None,
        endpoint: str = "https://api.openai.com/v1/chat/completions",
        max_retries: int = 2,
        concurrency: int = 3,
        timeout_seconds: float = 15,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_key.strip():
            raise CredentialsUnavailable("AISEO_OPENAI_API_KEY is required for generation")
        if not model or any(ch.isspace() for ch in model):
            raise ValueError("Invalid model identifier")
        if not 0 <= max_retries <= 3 or not 1 <= concurrency <= 16:
            raise ValueError("Retry or concurrency limit outside safe bounds")
        if not 1 <= timeout_seconds <= 60:
            raise ValueError("Invalid timeout")
        if not endpoint.startswith("https://"):
            raise ValueError("Provider endpoint must use HTTPS")
        self.model = model
        self.budget = budget
        self.pricing = pricing
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self._sleeper = sleeper
        self._semaphore = asyncio.Semaphore(concurrency)
        self._endpoint = endpoint
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(follow_redirects=False, trust_env=False)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _payload(
        self,
        request: GenerationRequest,
        schema: type[BaseModel] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        if request.max_output_tokens > self.budget.max_output_tokens:
            raise BudgetExceeded("Requested output tokens exceed the configured limit")
        prompt = template_for(request)
        json_schema = schema.model_json_schema() if schema else None
        messages = prompt.render(request, output_schema=json_schema)
        # A conservative offline guard; actual usage is checked against provider totals.
        # Counting UTF-8 bytes overestimates most tokenizers rather than undercounting.
        estimated_input_cap = len(
            json.dumps(messages, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        )
        if (
            estimated_input_cap > self.budget.max_input_tokens
            or estimated_input_cap + request.max_output_tokens > self.budget.max_total_tokens
        ):
            raise BudgetExceeded("Prompt exceeds the configured conservative input budget")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": request.max_output_tokens,
            "stream": stream,
            "store": False,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__[:64],
                    "schema": json_schema,
                    "strict": False,
                },
            }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _usage(self, raw: object, request: GenerationRequest) -> TokenUsage:
        if not isinstance(raw, dict):
            raise InvalidModelOutput("Provider omitted token usage")
        try:
            usage = TokenUsage(
                input_tokens=raw["prompt_tokens"],
                output_tokens=raw["completion_tokens"],
                total_tokens=raw["total_tokens"],
            )
        except (KeyError, ValueError, ValidationError, TypeError):
            raise InvalidModelOutput("Provider returned invalid token usage") from None
        if (
            usage.input_tokens > self.budget.max_input_tokens
            or usage.output_tokens > request.max_output_tokens
            or usage.total_tokens > self.budget.max_total_tokens
        ):
            raise BudgetExceeded("Provider token usage exceeded the configured budget")
        return usage

    def _cost(self, usage: TokenUsage) -> Decimal | None:
        return self.pricing.cost(usage) if self.pricing is not None else None

    async def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        delay = min(2.0, 0.25 * (2**attempt))
        if retry_after is not None:
            try:
                delay = max(delay, min(2.0, max(0.0, float(retry_after))))
            except ValueError:
                pass
        await self._sleeper(delay)

    @staticmethod
    def _status_error(response: httpx.Response) -> None:
        if response.status_code == 429:
            raise ProviderRateLimited("The AI provider rate limit was reached")
        if response.status_code >= 400:
            raise ProviderUnavailable("The AI provider could not complete this request")

    async def _post(self, payload: dict[str, Any]) -> tuple[httpx.Response, int]:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(
                    self._endpoint,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                )
            except httpx.TimeoutException:
                if attempt == self.max_retries:
                    raise LLMTimeout("AI provider timed out") from None
            except httpx.TransportError:
                if attempt == self.max_retries:
                    raise ProviderUnavailable("AI provider connection failed") from None
            else:
                if response.status_code not in _RETRYABLE or attempt == self.max_retries:
                    self._status_error(response)
                    return response, attempt
                await self._backoff(attempt, response.headers.get("Retry-After"))
                continue
            await self._backoff(attempt)
        raise ProviderUnavailable("AI provider retries exhausted")

    @overload
    async def complete(self, request: GenerationRequest, *, schema: type[T]) -> ModelResult[T]: ...

    @overload
    async def complete(
        self, request: GenerationRequest, *, schema: None = None
    ) -> ModelResult[BaseModel]: ...

    async def complete(
        self, request: GenerationRequest, *, schema: type[BaseModel] | None = None
    ) -> ModelResult[BaseModel]:
        with span("ai.generate", model=self.model, template_id=request.template_id) as observed:
            payload = self._payload(request, schema, stream=False)
            async with self._semaphore:
                response, retries = await self._post(payload)
            try:
                raw = response.json()
                if not isinstance(raw, dict) or not isinstance(raw.get("choices"), list):
                    raise ValueError
                choice = raw["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise InvalidModelOutput("Model response was incomplete or filtered")
                text = choice["message"]["content"]
                if not isinstance(text, str) or not text:
                    raise ValueError
            except (KeyError, IndexError, TypeError, ValueError):
                raise InvalidModelOutput("Provider returned an invalid completion") from None
            usage = self._usage(raw.get("usage"), request)
            if schema is None:
                result_value: str | BaseModel = text
            else:
                try:
                    result_value = schema.model_validate_json(text)
                except ValidationError:
                    raise InvalidModelOutput(
                        "Structured response did not match its schema"
                    ) from None
            observed.set(
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                retry_count=retries,
                estimated_cost_usd=str(self._cost(usage))
                if self._cost(usage) is not None
                else None,
            )
            logger.info(
                "LLM request finished model=%s tokens=%d template=%s",
                self.model,
                usage.total_tokens,
                request.template_id,
            )
            return ModelResult(
                value=result_value,
                model=self.model,
                usage=usage,
                cost_usd=self._cost(usage),
                prompt_id=request.template_id,
                prompt_version=request.template_version,
            )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        with span("ai.stream", model=self.model, template_id=request.template_id) as observed:
            """Emit text deltas and a measured usage event; never retry partial output."""
            payload = self._payload(request, None, stream=True)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.timeout_seconds * (self.max_retries + 1)
            deadline += self.max_retries * 2.0
            async with self._semaphore:
                # Only retry pre-stream HTTP failures. A partial stream is never replayed.
                for attempt in range(self.max_retries + 1):
                    try:
                        async with self._client.stream(
                            "POST",
                            self._endpoint,
                            json=payload,
                            headers=self._headers,
                            timeout=self.timeout_seconds,
                            follow_redirects=False,
                        ) as response:
                            if response.status_code in _RETRYABLE and attempt < self.max_retries:
                                await self._backoff(attempt, response.headers.get("Retry-After"))
                                continue
                            self._status_error(response)
                            finished = False
                            done = False
                            usage: TokenUsage | None = None
                            size = 0
                            async with asyncio.timeout_at(deadline):
                                async for line in response.aiter_lines():
                                    if not line.startswith("data:"):
                                        continue
                                    encoded = line[5:].strip()
                                    if encoded == _SSE_END:
                                        done = True
                                        break
                                    try:
                                        event = json.loads(encoded)
                                        if not isinstance(event, dict):
                                            raise ValueError
                                        if event.get("usage") is not None:
                                            usage = self._usage(event["usage"], request)
                                            yield StreamEvent(
                                                "usage", usage=usage, cost_usd=self._cost(usage)
                                            )
                                        for choice in event.get("choices", []):
                                            reason = choice.get("finish_reason")
                                            if reason is not None:
                                                if reason != "stop":
                                                    raise InvalidModelOutput(
                                                        "Stream ended without completion"
                                                    )
                                                finished = True
                                            delta = choice.get("delta", {}).get("content")
                                            if delta:
                                                if not isinstance(delta, str):
                                                    raise ValueError
                                                size += len(delta.encode("utf-8"))
                                                if size > request.max_output_tokens * 16:
                                                    raise BudgetExceeded(
                                                        "Streaming output exceeded byte guard"
                                                    )
                                                yield StreamEvent("delta", text=delta)
                                    except (TypeError, KeyError, ValueError):
                                        raise InvalidModelOutput(
                                            "Malformed provider stream event"
                                        ) from None
                            if not done or not finished or usage is None:
                                raise InvalidModelOutput(
                                    "Provider stream ended without final usage"
                                )
                            observed.set(
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                total_tokens=usage.total_tokens,
                                retry_count=attempt,
                                estimated_cost_usd=(
                                    str(self._cost(usage))
                                    if self._cost(usage) is not None
                                    else None
                                ),
                            )
                            yield StreamEvent("done", usage=usage, cost_usd=self._cost(usage))
                            logger.info(
                                "LLM stream finished model=%s tokens=%d",
                                self.model,
                                usage.total_tokens,
                            )
                            return
                    except (httpx.TimeoutException, TimeoutError):
                        # Once any part of a stream starts, replaying could duplicate output.
                        raise LLMTimeout("AI provider stream timed out") from None
                    except httpx.TransportError:
                        raise ProviderUnavailable("AI provider stream interrupted") from None
            raise ProviderUnavailable("AI provider stream retry budget exhausted")


def make_openai_provider(
    settings: Settings, *, client: httpx.AsyncClient | None = None
) -> OpenAIChatProvider:
    key = settings.openai_api_key
    if key is None or not key.get_secret_value().strip():
        raise CredentialsUnavailable("AISEO_OPENAI_API_KEY is required for generation")
    pricing = None
    if (
        settings.llm_input_usd_per_million is not None
        and settings.llm_output_usd_per_million is not None
    ):
        pricing = ModelPricing(
            input_usd_per_million=settings.llm_input_usd_per_million,
            output_usd_per_million=settings.llm_output_usd_per_million,
        )
    return OpenAIChatProvider(
        api_key=key.get_secret_value(),
        model=settings.llm_model,
        budget=TokenBudget(
            max_input_tokens=settings.llm_max_input_tokens,
            max_output_tokens=settings.llm_max_output_tokens,
            max_total_tokens=settings.llm_max_total_tokens,
        ),
        pricing=pricing,
        http_client=client,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        concurrency=settings.llm_concurrency,
    )
