"""Typed contracts for the optional, backend-only generation layer."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Generic, Literal, Protocol, TypeVar, overload

from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Controlled errors; never include raw prompts, keys, or provider response bodies."""

    code = "llm_error"


class CredentialsUnavailable(LLMError):
    code = "credentials_unavailable"


class ProviderUnavailable(LLMError):
    code = "provider_unavailable"


class ProviderRateLimited(LLMError):
    code = "provider_rate_limited"


class InvalidModelOutput(LLMError):
    code = "invalid_model_output"


class BudgetExceeded(LLMError):
    code = "budget_exceeded"


class LLMTimeout(LLMError):
    code = "llm_timeout"


class PromptNotFound(LLMError):
    code = "prompt_not_found"


class GenerationRequest(BaseModel):
    """Untrusted task/site text remains separate from trusted prompt instructions."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    template_id: str = Field(default="seo_explanation", pattern=r"^[a-z][a-z0-9_]{1,63}$")
    template_version: str = Field(default="v1", pattern=r"^v[1-9][0-9]{0,3}$")
    task: str = Field(min_length=1, max_length=4000)
    website_text: str = Field(default="", max_length=16000)
    max_output_tokens: int = Field(default=320, ge=32, le=2048)


class TokenBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_input_tokens: int = Field(default=4096, ge=128, le=100000)
    max_output_tokens: int = Field(default=512, ge=32, le=8192)
    max_total_tokens: int = Field(default=4608, ge=160, le=108192)

    @model_validator(mode="after")
    def sensible_total(self) -> "TokenBudget":
        if self.max_total_tokens < self.max_output_tokens:
            raise ValueError("Total token budget must cover the output limit")
        return self


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def accurate_totals(self) -> "TokenUsage":
        if self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("Token total is inconsistent")
        return self


class ModelPricing(BaseModel):
    """Optional configured prices; do not guess future prices from a model name."""

    model_config = ConfigDict(extra="forbid")
    input_usd_per_million: Decimal = Field(ge=0)
    output_usd_per_million: Decimal = Field(ge=0)

    def cost(self, usage: TokenUsage) -> Decimal:
        return (
            self.input_usd_per_million * usage.input_tokens
            + self.output_usd_per_million * usage.output_tokens
        ) / Decimal(1000000)


@dataclass(frozen=True)
class ModelResult(Generic[T]):
    value: str | T
    model: str
    usage: TokenUsage
    cost_usd: Decimal | None
    prompt_id: str
    prompt_version: str


@dataclass(frozen=True)
class StreamEvent:
    kind: Literal["delta", "usage", "done"]
    text: str = ""
    usage: TokenUsage | None = None
    cost_usd: Decimal | None = None


class LLMProvider(Protocol):
    @overload
    async def complete(self, request: GenerationRequest, *, schema: type[T]) -> ModelResult[T]: ...

    @overload
    async def complete(
        self, request: GenerationRequest, *, schema: None = None
    ) -> ModelResult[BaseModel]: ...

    async def complete(
        self, request: GenerationRequest, *, schema: type[BaseModel] | None = None
    ) -> ModelResult[BaseModel]: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]: ...
