"""FastAPI application factory."""

from fastapi import FastAPI

from aiseoonline_api import __version__
from aiseoonline_api.config import Settings, get_settings
from aiseoonline_api.logging import configure_logging
from aiseoonline_api.routes.health import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application; passing settings keeps tests isolated."""
    resolved = settings if settings is not None else get_settings()
    configure_logging(resolved.log_level)

    application = FastAPI(
        title=resolved.app_name,
        description="HTTP API for AISEOOnline SEO utilities.",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    application.state.settings = resolved
    application.include_router(health_router, prefix="/api/v1")
    return application


app = create_app()
