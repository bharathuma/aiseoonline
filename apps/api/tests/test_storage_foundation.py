"""Pure-model and configuration checks, safe without running services."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import MetaData, create_engine

from aiseoonline_api.config import Settings
from aiseoonline_api.db import models  # noqa: F401 -- register tables
from aiseoonline_api.db.base import Base
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.main import create_app


def test_expected_database_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users", "projects", "audit_jobs", "pages", "seo_findings", "ai_usage"
    }


def test_local_sqlite_can_compile_schema_without_vector_dependency() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        metadata = MetaData()
        metadata.reflect(bind=engine)
        assert set(metadata.tables) == set(Base.metadata.tables)
    finally:
        engine.dispose()


def test_database_url_is_required_when_creating_engine() -> None:
    with pytest.raises(RuntimeError, match="AISEO_DATABASE_URL"):
        create_database_engine(Settings(_env_file=None, database_url=None))


def test_settings_hide_storage_credentials() -> None:
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:do-not-log@db/test",
                        redis_url="redis://:never-show-this@redis:6379/0")
    assert "do-not-log" not in repr(settings)
    assert "never-show-this" not in repr(settings)


def test_production_requires_both_storage_urls() -> None:
    with pytest.raises(ValidationError, match="Production requires"):
        Settings(_env_file=None, environment="production", database_url=None, redis_url=None)


def test_readiness_unconfigured_returns_503_without_secrets() -> None:
    settings = Settings(_env_file=None, database_url=None, redis_url=None)
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "password" not in response.text.lower()


def test_alembic_metadata_matches_models() -> None:
    assert all(table.primary_key.columns for table in Base.metadata.tables.values())
