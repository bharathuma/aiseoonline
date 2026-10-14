"""Create engines only when a database connection is requested."""

from sqlalchemy import Engine, create_engine

from aiseoonline_api.config import Settings


def create_database_engine(settings: Settings) -> Engine:
    url = settings.require_database_url()
    if not url.startswith(("postgresql+psycopg://", "sqlite://")):
        raise ValueError("AISEO_DATABASE_URL must use postgresql+psycopg or sqlite")
    return create_engine(url, pool_pre_ping=True)
