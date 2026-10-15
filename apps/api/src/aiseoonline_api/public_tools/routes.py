"""Anonymous tool endpoints with shared Redis budgets and safe error responses."""

import asyncio
import hashlib
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from redis import Redis
from redis.exceptions import RedisError

from aiseoonline_api.crawler import (
    CrawlError,
    CrawlLimitExceeded,
    CrawlTimeout,
    HttpStatusError,
    InvalidPage,
    NetworkFailure,
    RobotsDenied,
    UnsafeTarget,
    normalize_url,
)
from aiseoonline_api.errors import error_response
from aiseoonline_api.public_tools.advanced import (
    check_canonical,
    check_redirects,
    check_schema,
)
from aiseoonline_api.public_tools.checks import (
    ToolReport,
    check_meta,
    check_robots,
    check_sitemap,
)
from aiseoonline_api.public_tools.final_tools import check_headings, check_links, check_social

router = APIRouter(tags=["public SEO tools"])
Tool = Literal[
    "robots", "sitemap", "meta", "redirects", "canonical", "schema", "headings", "links", "social"
]
_LIMIT_SCRIPT = """
local a=redis.call('INCR', KEYS[1])
if a==1 then redis.call('EXPIRE', KEYS[1], 3600) end
local b=redis.call('INCR', KEYS[2])
if b==1 then redis.call('EXPIRE', KEYS[2], 3600) end
if a>tonumber(ARGV[1]) or b>tonumber(ARGV[2]) then return 0 end
return 1
"""


class UrlInput(BaseModel):
    url: str = Field(min_length=12, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        try:
            return normalize_url(value).value
        except UnsafeTarget:
            raise ValueError("A public HTTP(S) URL is required") from None


def _check_quota(url: str, peer: str, redis_url: str) -> bool:
    # No forwarded-IP headers are trusted; the reverse proxy must be configured
    # explicitly before deploying traffic-based per-visitor limits.
    host = normalize_url(url).host
    ip_hash = hashlib.sha256(peer.encode()).hexdigest()
    host_hash = hashlib.sha256(host.encode()).hexdigest()
    with Redis.from_url(redis_url, socket_connect_timeout=0.6, socket_timeout=0.6) as client:
        return bool(
            client.eval(_LIMIT_SCRIPT, 2, f"seo:ip:{ip_hash}", f"seo:site:{host_hash}", 12, 120)
        )


async def reserve_budget(request: Request, url: str) -> bool | None:
    settings = request.app.state.settings
    if settings.redis_url is None:
        return None
    peer = request.client.host if request.client else "unknown"
    try:
        return await asyncio.to_thread(_check_quota, url, peer, settings.require_redis_url())
    except (RedisError, OSError, TimeoutError):
        return None


async def execute(request: Request, body: UrlInput, tool: Tool) -> ToolReport | JSONResponse:
    permitted = await reserve_budget(request, body.url)
    if permitted is None:
        return error_response(
            request, 503, "service_unavailable", "Public checks are temporarily unavailable."
        )
    if not permitted:
        response = error_response(
            request,
            429,
            "rate_limited",
            "Free checks are limited to 12/hour per visitor and 120/hour per site.",
        )
        response.headers["Retry-After"] = "3600"
        return response
    fn = {
        "robots": check_robots,
        "sitemap": check_sitemap,
        "meta": check_meta,
        "redirects": check_redirects,
        "canonical": check_canonical,
        "schema": check_schema,
        "headings": check_headings,
        "links": check_links,
        "social": check_social,
    }[tool]
    slots: asyncio.Semaphore = request.app.state.public_tool_slots
    try:
        async with asyncio.timeout(16):
            async with slots:
                return await asyncio.to_thread(fn, body.url)
    except UnsafeTarget:
        return error_response(
            request, 400, "unsafe_target", "The destination must be a public HTTP(S) site."
        )
    except RobotsDenied:
        return error_response(request, 403, "robots_denied", "The site does not permit this check.")
    except CrawlLimitExceeded:
        return error_response(
            request, 413, "crawl_limit", "The site exceeds this free check's resource limits."
        )
    except (CrawlTimeout, TimeoutError):
        return error_response(request, 504, "site_timeout", "The site did not respond in time.")
    except HttpStatusError as exc:
        return error_response(
            request, 502, "site_http_error", f"The website returned HTTP {exc.status_code}."
        )
    except NetworkFailure:
        return error_response(request, 502, "site_unreachable", "The website could not be reached.")
    except (InvalidPage, ValueError):
        return error_response(
            request, 422, "invalid_document", "The fetched document cannot be analyzed safely."
        )
    except CrawlError:
        return error_response(request, 502, "crawl_failed", "The site could not be checked.")


@router.post("/tools/robots", response_model=ToolReport, summary="Inspect robots.txt syntax")
async def robots(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "robots")


@router.post("/tools/sitemap", response_model=ToolReport, summary="Validate XML sitemap")
async def sitemap(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "sitemap")


@router.post("/tools/meta", response_model=ToolReport, summary="Inspect page metadata")
async def metadata(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "meta")


@router.post(
    "/tools/redirects", response_model=ToolReport, summary="Inspect a bounded redirect chain"
)
async def redirects(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "redirects")


@router.post(
    "/tools/canonical", response_model=ToolReport, summary="Inspect HTML canonical declarations"
)
async def canonical(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "canonical")


@router.post(
    "/tools/schema", response_model=ToolReport, summary="Check JSON-LD syntax and structure"
)
async def schema(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "schema")


@router.post("/tools/headings", response_model=ToolReport, summary="Review HTML heading outline")
async def headings(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "headings")


@router.post("/tools/links", response_model=ToolReport, summary="Check bounded internal links")
async def links(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "links")


@router.post("/tools/social", response_model=ToolReport, summary="Inspect social sharing metadata")
async def social(request: Request, body: UrlInput) -> ToolReport | JSONResponse:
    return await execute(request, body, "social")
