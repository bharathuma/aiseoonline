"""Deterministic, offline-only provider for unit tests and documentation."""

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import TypeVar, overload

from pydantic import BaseModel, ValidationError

from aiseoonline_api.ai_core.contracts import (
    GenerationRequest,
    InvalidModelOutput,
    ModelResult,
    StreamEvent,
    TokenUsage,
)
from aiseoonline_api.ai_core.prompts import template_for

T = TypeVar("T", bound=BaseModel)


class FixtureProvider:
    """Returns explicitly configured fixture data, not a simulated model result."""

    def __init__(
        self,
        *,
        text: str,
        usage: TokenUsage,
        deltas: tuple[str, ...] | None = None,
    ) -> None:
        self.text = text
        self.usage = usage
        self.deltas = deltas or (text,)
        self.calls: list[GenerationRequest] = []

    @overload
    async def complete(
        self, request: GenerationRequest, *, schema: type[T]
    ) -> ModelResult[T]: ...

    @overload
    async def complete(
        self, request: GenerationRequest, *, schema: None = None
    ) -> ModelResult[BaseModel]: ...

    async def complete(
        self, request: GenerationRequest, *, schema: type[BaseModel] | None = None
    ) -> ModelResult[BaseModel]:
        template_for(request)
        self.calls.append(request)
        if schema is None:
            value: str | BaseModel = self.text
        else:
            try:
                value = schema.model_validate_json(self.text)
            except ValidationError:
                raise InvalidModelOutput("Fixture does not satisfy structured schema") from None
        return ModelResult(
            value=value, model="fixture", usage=self.usage, cost_usd=Decimal(0),
            prompt_id=request.template_id, prompt_version=request.template_version,
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        template_for(request)
        self.calls.append(request)
        for part in self.deltas:
            yield StreamEvent(kind="delta", text=part)
        yield StreamEvent(kind="usage", usage=self.usage, cost_usd=Decimal(0))
        yield StreamEvent(kind="done", usage=self.usage, cost_usd=Decimal(0))
