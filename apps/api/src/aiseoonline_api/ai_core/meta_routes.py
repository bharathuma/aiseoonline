"""Anonymous AI meta suggestions with atomic Redis budgets and no paid-call fallback."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_CEILING
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
from redis import Redis
from redis.exceptions import RedisError

from aiseoonline_api.ai_core import (
    BudgetExceeded,
    CredentialsUnavailable,
    GenerationRequest,
    InvalidModelOutput,
    LLMTimeout,
    ProviderRateLimited,
    ProviderUnavailable,
    make_openai_provider,
)
from aiseoonline_api.ai_core.meta_generator import (
    MetaDraft,
    MetaGeneratorResponse,
    review_draft,
)
from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import (
    CrawlError,
    CrawlSession,
    HttpStatusError,
    RobotsDenied,
    UnsafeTarget,
    normalize_url,
)
from aiseoonline_api.errors import error_response

router = APIRouter(tags=["AI SEO tools"])
_CACHE_SECONDS = 900
_PROMPT_TASK = (
    "Create exactly three distinct, useful SEO title and meta description pairs. "
    "Use only the provided source content. Each pair must include an exact contiguous "
    "5–240 character evidence_quote copied from the source, plus a specific rationale. "
    "Do not invent numbers, discounts, rankings, prices, credentials or promises. "
    "Titles and descriptions must be genuinely different, relevant and readable."
)
_PEER_SCRIPT = """
local count=tonumber(redis.call('GET', KEYS[1]) or '0')
if count>=3 then return -2 end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 3600)
return 3-count-1
"""
_SPEND_SCRIPT = """
local spent=tonumber(redis.call('GET', KEYS[1]) or '0')
if spent+tonumber(ARGV[1])>tonumber(ARGV[2]) then return -1 end
redis.call('INCRBY', KEYS[1], ARGV[1])
if spent==0 then redis.call('EXPIRE', KEYS[1], 90000) end
return 1
"""


class MetaGeneratorInput(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    content: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def one_source(self) -> "MetaGeneratorInput":
        if bool(self.url) == bool(self.content):
            raise ValueError("Provide either one public URL or pasted content")
        if self.url:
            try:
                self.url = normalize_url(self.url).value
            except UnsafeTarget:
                raise ValueError("A public HTTP(S) URL is required") from None
        else:
            self.content = " ".join((self.content or "").split())
            if len(self.content) < 100:
                raise ValueError("Provide at least 100 characters of meaningful content")
        return self


def _price_micro(settings: Settings, output_tokens: int) -> int | None:
    """Reserve the whole retry envelope rather than assuming successful billing."""
    if settings.llm_input_usd_per_million is None or settings.llm_output_usd_per_million is None:
        return None
    estimate = (
        settings.llm_input_usd_per_million * settings.llm_max_input_tokens
        + settings.llm_output_usd_per_million * output_tokens
    )
    return int(
        (estimate * (settings.llm_max_retries + 1)).to_integral_value(rounding=ROUND_CEILING)
    )


def _limits(settings: Settings) -> tuple[int, int] | None:
    max_output = min(480, settings.llm_max_output_tokens)
    if settings.llm_max_total_tokens < max_output + settings.llm_max_input_tokens:
        return None
    allocation = _price_micro(settings, max_output)
    if allocation is None or allocation < 1:
        return None
    per_request = int(settings.ai_meta_request_usd_cap * 1_000_000)
    daily = int(settings.ai_meta_daily_usd_cap * 1_000_000)
    if allocation > per_request:
        return None
    return allocation, daily


def _check_peer(redis_url: str, peer: str) -> int:
    peer_key = hashlib.sha256(peer.encode()).hexdigest()
    with Redis.from_url(redis_url, socket_timeout=0.8, socket_connect_timeout=0.8) as client:
        return int(client.eval(_PEER_SCRIPT, 1, f"ai:peer:{peer_key}"))


def _reserve_spend(redis_url: str, allocation: int, limit: int) -> bool:
    with Redis.from_url(redis_url, socket_timeout=0.8, socket_connect_timeout=0.8) as client:
        return (
            int(
                client.eval(
                    _SPEND_SCRIPT,
                    1,
                    "ai:daily:" + datetime.now(UTC).strftime("%Y%m%d"),
                    allocation,
                    limit,
                )
            )
            == 1
        )


def _source_from_url(url: str) -> tuple[str, str]:
    page = CrawlSession(url).fetch_page()
    descriptions = [m.content for m in page.html.meta if m.name.casefold() == "description"][:2]
    headings = [h.text for h in page.html.headings if h.text][:12]
    parts = [page.html.title or "", *descriptions, *headings]
    content = " ".join(part for part in parts if part).strip()
    if len(content) < 60:
        raise ValueError("Page metadata contains too little readable source evidence")
    return content[:3000], page.final_url


def _cache_key(text: str, url: str | None, model: str) -> str | None:
    if url is None:
        return None  # Never cache pasted or potentially sensitive visitor text.
    value = json.dumps(["v1", model, url, text], separators=(",", ":"))
    return "ai:meta:cache:" + hashlib.sha256(value.encode()).hexdigest()


def _cached_result(raw: str) -> MetaGeneratorResponse | None:
    try:
        return MetaGeneratorResponse.model_validate_json(raw)
    except ValueError:
        return None


def _store_cache(redis_url: str, key: str, result: MetaGeneratorResponse) -> None:
    with Redis.from_url(redis_url, socket_timeout=0.8, socket_connect_timeout=0.8) as client:
        client.setex(key, _CACHE_SECONDS, result.model_dump_json())


@router.post(
    "/tools/ai-meta",
    response_model=MetaGeneratorResponse,
    summary="Generate source-grounded SEO titles and descriptions",
)
async def ai_meta(
    request: Request, body: MetaGeneratorInput
) -> MetaGeneratorResponse | JSONResponse:
    settings: Settings = request.app.state.settings
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value().strip():
        return error_response(
            request,
            503,
            "ai_not_configured",
            "AI suggestions are not currently available. Try a free metadata checker.",
        )
    limits = _limits(settings)
    if limits is None:
        return error_response(
            request,
            503,
            "ai_budget_not_configured",
            "AI spending limits are not configured. Free SEO checks remain available.",
        )
    if settings.redis_url is None:
        return error_response(
            request, 503, "service_unavailable", "AI usage limits are temporarily unavailable."
        )

    # Protect expensive URL fetching before requesting any external resource.
    peer = request.client.host if request.client else "unknown"
    redis_url = settings.require_redis_url()
    try:
        remaining = await asyncio.to_thread(_check_peer, redis_url, peer)
    except (RedisError, OSError, TimeoutError, ValueError):
        return error_response(
            request, 503, "service_unavailable", "AI usage limits are temporarily unavailable."
        )
    if remaining == -2:
        reply = error_response(
            request,
            429,
            "ai_rate_limited",
            "AI suggestions are limited to three requests per hour per visitor.",
        )
        reply.headers["Retry-After"] = "3600"
        return reply

    try:
        if body.url:
            async with asyncio.timeout(13):
                evidence, source_url = await asyncio.to_thread(_source_from_url, body.url)
            source_type: Literal["url", "text"] = "url"
        else:
            evidence, source_url = body.content or "", None
            source_type = "text"
    except RobotsDenied:
        return error_response(request, 403, "robots_denied", "This page disallows crawling.")
    except HttpStatusError:
        return error_response(request, 502, "site_http_error", "The site returned an HTTP error.")
    except (CrawlError, TimeoutError):
        return error_response(
            request, 502, "site_unreachable", "The page could not be safely read."
        )
    except ValueError:
        return error_response(
            request, 422, "insufficient_evidence", "The page contains too little SEO content."
        )

    cache_key = _cache_key(evidence, source_url, settings.llm_model)
    if cache_key:
        try:
            with Redis.from_url(redis_url, socket_timeout=0.8) as redis_client:
                raw = redis_client.get(cache_key)
            cache_hit = _cached_result(raw.decode()) if raw else None
            if cache_hit:
                return cache_hit.model_copy(
                    update={
                        "cached": True,
                        "usage": None,
                        "estimated_cost_usd": None,
                        "visitor_message": "Cached suggestions; no new AI call was made.",
                    }
                )
        except (RedisError, OSError, TimeoutError):
            return error_response(
                request, 503, "service_unavailable", "AI caching is temporarily unavailable."
            )

    try:
        allowed = await asyncio.to_thread(_reserve_spend, redis_url, limits[0], limits[1])
    except (RedisError, OSError, TimeoutError):
        return error_response(
            request, 503, "service_unavailable", "AI spending limits are unavailable."
        )
    if not allowed:
        reply = error_response(
            request,
            429,
            "ai_daily_budget_reached",
            "The AI spending allocation has been exhausted. Try again later.",
        )
        reply.headers["Retry-After"] = "3600"
        return reply

    # App-wide slot bound is independent of per-provider semaphores.
    slots: asyncio.Semaphore = request.app.state.ai_meta_slots
    provider = make_openai_provider(settings)
    try:
        async with asyncio.timeout(52):
            async with slots:
                answer = await provider.complete(
                    GenerationRequest(
                        template_id="meta_draft",
                        template_version="v1",
                        task=_PROMPT_TASK,
                        website_text=evidence,
                        max_output_tokens=min(480, settings.llm_max_output_tokens),
                    ),
                    schema=MetaDraft,
                )
        if not isinstance(answer.value, MetaDraft):
            raise InvalidModelOutput("Model did not return a typed SEO draft")
        reviewed = review_draft(answer.value, evidence)
        response = MetaGeneratorResponse(
            suggestions=reviewed,
            source_type=source_type,
            source_url=source_url,
            source_summary="Extracted title, description and headings"
            if body.url
            else "Visitor-provided text",
            model=answer.model,
            cached=False,
            usage=answer.usage.model_dump(),
            estimated_cost_usd=str(answer.cost_usd) if answer.cost_usd is not None else None,
            visitor_message="Three AI drafts generated. Review accuracy before publishing.",
        )
        if cache_key:
            try:
                await asyncio.to_thread(_store_cache, redis_url, cache_key, response)
            except (RedisError, OSError, TimeoutError):
                pass  # Generation succeeded; do not misrepresent an uncached answer.
        return response
    except (BudgetExceeded, InvalidModelOutput):
        return error_response(
            request, 502, "ai_invalid_output", "AI did not produce verified suggestions."
        )
    except (
        ProviderRateLimited,
        ProviderUnavailable,
        CredentialsUnavailable,
        LLMTimeout,
        TimeoutError,
    ):
        return error_response(
            request,
            503,
            "ai_temporarily_unavailable",
            "AI is temporarily unavailable. Please try the free metadata checker.",
        )
    finally:
        await provider.aclose()
