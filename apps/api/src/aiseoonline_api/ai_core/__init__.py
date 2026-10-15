"""Optional provider infrastructure; no AI calls are made at application startup."""

from aiseoonline_api.ai_core.contracts import (
    BudgetExceeded,
    CredentialsUnavailable,
    GenerationRequest,
    InvalidModelOutput,
    LLMError,
    LLMProvider,
    LLMTimeout,
    ModelPricing,
    ModelResult,
    PromptNotFound,
    ProviderRateLimited,
    ProviderUnavailable,
    StreamEvent,
    TokenBudget,
    TokenUsage,
)
from aiseoonline_api.ai_core.fixture_provider import FixtureProvider
from aiseoonline_api.ai_core.openai_provider import OpenAIChatProvider, make_openai_provider
from aiseoonline_api.ai_core.prompts import available_prompts, template_for

__all__ = [
    "BudgetExceeded", "CredentialsUnavailable", "FixtureProvider", "GenerationRequest",
    "InvalidModelOutput", "LLMError", "LLMProvider", "LLMTimeout", "ModelPricing",
    "ModelResult", "OpenAIChatProvider", "PromptNotFound", "ProviderRateLimited",
    "ProviderUnavailable", "StreamEvent", "TokenBudget", "TokenUsage",
    "available_prompts", "make_openai_provider", "template_for",
]
