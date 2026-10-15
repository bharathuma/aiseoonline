"""Development-only private project chat; production is always disabled."""

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from aiseoonline_api.ai_core import (
    BudgetExceeded,
    CredentialsUnavailable,
    InvalidModelOutput,
    LLMTimeout,
    ProviderRateLimited,
    ProviderUnavailable,
    make_openai_provider,
)
from aiseoonline_api.config import Settings
from aiseoonline_api.errors import error_response
from aiseoonline_api.rag.assistant import (
    GroundedAnswer,
    QuestionInput,
    answer_question,
    check_project,
    collect_evidence,
)
from aiseoonline_api.rag.embeddings import make_openai_embedding_provider
from aiseoonline_api.rag.retrieval import HybridRetriever
from aiseoonline_api.rag.store import RagAccessDenied

router = APIRouter(tags=["Internal development RAG assistant"])

_GUARD_SCRIPT = """
local count=tonumber(redis.call('GET', KEYS[1]) or '0')
if count>=tonumber(ARGV[1]) then return -2 end
local allocated=tonumber(redis.call('GET', KEYS[2]) or '0')
if allocated+tonumber(ARGV[2])>tonumber(ARGV[3]) then return -1 end
redis.call('INCR', KEYS[1])
if count==0 then redis.call('EXPIRE', KEYS[1], 3600) end
redis.call('INCRBY', KEYS[2], ARGV[2])
if allocated==0 then redis.call('EXPIRE', KEYS[2], 90000) end
return 1
"""


def dev_access(request: Request, settings: Settings) -> bool:
    if settings.environment not in ("development", "test") or not settings.rag_chat_enabled:
        return False
    token = settings.rag_chat_dev_token
    incoming = request.headers.get("x-dev-rag-token", "")
    if token is None or len(incoming) < 24 or len(incoming) > 256:
        return False
    if request.client is None or request.client.host not in ("127.0.0.1", "::1", "testclient"):
        return False
    return hmac.compare_digest(token.get_secret_value(), incoming)


def price_allocation(settings: Settings) -> int | None:
    input_rate = settings.llm_input_usd_per_million
    output_rate = settings.llm_output_usd_per_million
    embed_rate = settings.rag_chat_embedding_usd_per_million
    if input_rate is None or output_rate is None or embed_rate is None:
        return None
    if settings.llm_max_input_tokens < 5500 or settings.llm_max_output_tokens < 480:
        return None
    # Conservative reserve: full context budget + retry envelope for generation
    # and all 3 embedding retries. Actual costs are provider-controlled.
    worst_micro_usd = (input_rate * settings.llm_max_input_tokens + output_rate * 480) * (
        settings.llm_max_retries + 1
    ) + embed_rate * 800 * 3
    allocation = int(worst_micro_usd.to_integral_value(rounding=ROUND_CEILING))
    request_limit = int(settings.rag_chat_request_usd_cap * Decimal(1000000))
    return allocation if 0 < allocation <= request_limit else None


def reserve(redis_url: str, visitor: str, allocation: int, cap: int) -> int:
    peer = hashlib.sha256(visitor.encode("utf-8")).hexdigest()
    date = datetime.now(UTC).strftime("%Y%m%d")
    with Redis.from_url(redis_url, socket_timeout=0.8, socket_connect_timeout=0.8) as client:
        result = client.eval(
            _GUARD_SCRIPT,
            2,
            f"ai:rag:peer:{peer}",
            f"ai:rag:daily:{date}",
            6,
            allocation,
            cap,
        )
    return int(result)


def preauthorize(request: Request, project_id: UUID, owner_id: UUID) -> None:
    engine = request.app.state.database_engine
    if engine is None:
        raise RuntimeError("Database connection is unavailable")
    with Session(engine) as session:
        check_project(session, project_id, owner_id)


def retrieve_sources(request: Request, question: QuestionInput, owner_id: UUID):
    engine = request.app.state.database_engine
    if engine is None:
        raise RuntimeError("Database connection is unavailable")
    settings: Settings = request.app.state.settings
    embedding = make_openai_embedding_provider(settings)
    try:
        with Session(engine) as session:
            retrieval = HybridRetriever(session, embedding)
            return collect_evidence(
                session,
                retrieval,
                project_id=question.project_id,
                owner_id=owner_id,
                question=question.question,
            )
    finally:
        embedding.close()


@router.post(
    "/internal/rag/chat",
    response_model=GroundedAnswer,
    summary="Development-only verified-project evidence chat",
)
async def chat(request: Request, question: QuestionInput) -> GroundedAnswer | JSONResponse:
    settings: Settings = request.app.state.settings
    if not dev_access(request, settings):
        # Do not advertise an available private service in production.
        return error_response(request, 404, "not_found", "The requested resource was not found.")
    if settings.database_url is None or settings.redis_url is None:
        return error_response(
            request, 503, "service_unavailable", "Private chat dependencies unavailable."
        )
    if settings.openai_api_key is None:
        return error_response(request, 503, "ai_not_configured", "AI credentials unavailable.")
    allocation = price_allocation(settings)
    if allocation is None:
        return error_response(request, 503, "ai_budget_not_configured", "AI budgets unavailable.")

    # Owner identity is bound to the server-side configured development session,
    # never accepted from the browser as an owner_id.
    owner_id = settings.rag_chat_dev_owner_id
    if owner_id is None:
        return error_response(
            request, 503, "dev_identity_missing", "Development identity unavailable."
        )

    try:
        await asyncio.to_thread(preauthorize, request, question.project_id, owner_id)
    except RagAccessDenied:
        return error_response(request, 404, "not_found", "Project is unavailable.")
    except (RuntimeError, OSError):
        return error_response(request, 503, "service_unavailable", "Database is unavailable.")

    try:
        cap = int(settings.rag_chat_daily_usd_cap * Decimal(1000000))
        peer = request.client.host if request.client else "unknown"
        admitted = await asyncio.to_thread(
            reserve,
            settings.require_redis_url(),
            peer,
            allocation,
            cap,
        )
    except (RedisError, ValueError, OSError, TimeoutError):
        return error_response(
            request, 503, "service_unavailable", "Usage controls are unavailable."
        )
    if admitted != 1:
        response = error_response(
            request,
            429,
            "rag_chat_budget_exhausted",
            "Private assistant request limit or budget exhausted.",
        )
        response.headers["Retry-After"] = "3600"
        return response

    slots: asyncio.Semaphore = request.app.state.rag_chat_slots
    try:
        async with slots, asyncio.timeout(52):
            sources = await asyncio.to_thread(retrieve_sources, request, question, owner_id)
            # No evidence means no paid generation call.
            if not sources:
                return GroundedAnswer(
                    project_id=question.project_id,
                    statements=[],
                    sources=[],
                    uncertainty="No relevant indexed content or completed findings were found.",
                )
            model = make_openai_provider(settings)
            try:
                return await answer_question(question.project_id, question, sources, model)
            finally:
                await model.aclose()
    except RagAccessDenied:
        return error_response(request, 404, "not_found", "Project is unavailable.")
    except (
        CredentialsUnavailable,
        ProviderUnavailable,
        ProviderRateLimited,
        LLMTimeout,
        TimeoutError,
    ):
        return error_response(
            request, 503, "ai_unavailable", "Private assistant is temporarily unavailable."
        )
    except (BudgetExceeded, InvalidModelOutput, ValueError):
        return error_response(
            request, 502, "ungrounded_answer", "No verifiable answer could be produced."
        )
