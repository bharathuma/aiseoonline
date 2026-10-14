"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aiseoonline_api import __version__
from aiseoonline_api.config import Settings, get_settings
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.logging import configure_logging
from aiseoonline_api.routes.health import router as health_router
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
    application.state.database_engine = (
        create_database_engine(resolved) if resolved.database_url is not None else None
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(readiness_router, prefix="/api/v1")
    return application


app = create_app()
