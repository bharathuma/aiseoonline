"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aiseoonline_api import __version__
from aiseoonline_api.agents.routes import router as audit_jobs_router
from aiseoonline_api.ai_core.meta_routes import router as ai_meta_router
from aiseoonline_api.config import Settings, get_settings
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.errors import ERROR_RESPONSES, register_error_handlers
from aiseoonline_api.logging import configure_logging
from aiseoonline_api.public_tools.routes import router as public_tools_router
from aiseoonline_api.rag.chat_routes import router as rag_chat_router
from aiseoonline_api.request_id import RequestIdMiddleware
from aiseoonline_api.routes.health import router as health_router
from aiseoonline_api.routes.readiness import ReadinessResponse
from aiseoonline_api.routes.readiness import router as readiness_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API; database connections are established lazily by SQLAlchemy."""
    resolved = settings if settings is not None else get_settings()
    configure_logging(resolved.log_level)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if application.state.database_engine is not None:
                application.state.database_engine.dispose()

    application = FastAPI(
        title=resolved.app_name,
        description="HTTP API for AISEOOnline SEO utilities.",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
        lifespan=lifespan,
    )
    application.state.settings = resolved
    application.state.public_tool_slots = asyncio.Semaphore(4)
    application.state.ai_meta_slots = asyncio.Semaphore(2)
    application.state.rag_chat_slots = asyncio.Semaphore(2)
    application.state.database_engine = (
        create_database_engine(resolved) if resolved.database_url is not None else None
    )
    register_error_handlers(application)
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health_router, prefix="/api/v1", responses=ERROR_RESPONSES)
    application.include_router(public_tools_router, prefix="/api/v1", responses=ERROR_RESPONSES)
    application.include_router(ai_meta_router, prefix="/api/v1", responses=ERROR_RESPONSES)
    if resolved.environment != "production":
        application.include_router(rag_chat_router, prefix="/api/v1", responses=ERROR_RESPONSES)
        application.include_router(audit_jobs_router, prefix="/api/v1", responses=ERROR_RESPONSES)
    application.include_router(
        readiness_router,
        prefix="/api/v1",
        responses={
            **ERROR_RESPONSES,
            503: {"model": ReadinessResponse, "description": "Dependency readiness unavailable"},
        },
    )
    return application


app = create_app()
