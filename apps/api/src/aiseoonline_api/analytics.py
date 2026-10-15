"""Disabled-by-default, consent-only aggregate counts of public page visits.

No identifiers, URL queries, user agents, IP addresses or page text are stored
by this application. Host/CDN transport logs are governed separately.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from redis.exceptions import RedisError

from aiseoonline_api.errors import error_response

router = APIRouter(tags=["Optional first-party analytics"])

# Explicit reviewed path allowlist prevents recording sensitive or arbitrary URLs.
PUBLIC_PATHS = frozenset(
    {
        "/",
        "/tools/",
        "/audit/",
        "/guides/",
        "/docs/",
        "/open-source/",
        "/open-source/benchmarks/",
        "/guides/title-tags/",
        "/guides/robots-txt-basics/",
        "/about/",
        "/contact/",
        "/privacy/",
        "/terms/",
        "/tools/robots-txt-validator/",
        "/tools/xml-sitemap-validator/",
        "/tools/meta-tag-checker/",
        "/tools/redirect-chain-checker/",
        "/tools/canonical-url-checker/",
        "/tools/structured-data-checker/",
        "/tools/heading-structure-analyzer/",
        "/tools/internal-link-checker/",
        "/tools/social-metadata-checker/",
        "/tools/ai-meta-suggestions/",
    }
)

_LUA = """
local previous = redis.call('GET', KEYS[1])
if previous and tonumber(previous) >= tonumber(ARGV[1]) then return 0 end
local value = redis.call('INCR', KEYS[1])
if value == 1 then redis.call('EXPIRE', KEYS[1], 2592000) end
return 1
"""


class PageView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=90, min_length=1)


@router.post("/analytics/pageview", status_code=204)
def record_pageview(payload: PageView, request: Request) -> Response:
    settings = request.app.state.settings
    if not settings.analytics_enabled:
        return error_response(request, 404, "not_found", "Analytics are not enabled.")
    if payload.path not in PUBLIC_PATHS:
        return error_response(request, 422, "invalid_path", "Only public page paths are accepted.")
    if settings.redis_url is None:
        return error_response(request, 503, "service_unavailable", "Analytics are unavailable.")
    key = "analytics:v1:" + datetime.now(UTC).strftime("%Y%m%d") + ":" + payload.path
    try:
        with Redis.from_url(
            settings.require_redis_url(),
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        ) as redis:
            accepted = redis.eval(_LUA, 1, key, 10000)
    except (RedisError, OSError, ValueError, TimeoutError):
        return error_response(request, 503, "service_unavailable", "Analytics are unavailable.")
    if not accepted:
        return error_response(request, 429, "rate_limited", "Daily count limit reached.")
    return Response(status_code=204, headers={"Cache-Control": "no-store"})
