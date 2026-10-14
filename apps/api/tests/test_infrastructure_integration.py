"""Real PostgreSQL/Redis integration tests when CI provides service URLs."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text

from aiseoonline_api.config import Settings
from aiseoonline_api.db.models import Project, User
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.main import create_app


@pytest.mark.integration
def test_postgres_migration_and_database_round_trip() -> None:
    url = os.environ.get("AISEO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL service not configured")
    engine = create_database_engine(Settings(_env_file=None, database_url=url))
    try:
        with engine.begin() as conn:
            names = inspect(conn).get_table_names()
            required = {"users", "projects", "audit_jobs", "pages", "seo_findings", "ai_usage"}
            assert required.issubset(names)
            extension = conn.scalar(text("SELECT extname FROM pg_extension WHERE extname='vector'"))
            assert extension == "vector"
        # Round trip inside a transaction that is rolled back to keep the test database clean.
        with engine.connect() as conn:
            transaction = conn.begin()
            from sqlalchemy.orm import Session

            with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
                user = User(email=f"integration-{uuid4().hex}@example.test")
                session.add(user)
                session.flush()
                project = Project(owner_id=user.id, domain="example.test")
                session.add(project)
                session.flush()
                selected = session.scalar(select(Project.domain).where(Project.id == project.id))
                assert selected == "example.test"
            transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.integration
def test_redis_ping_and_example_worker_round_trip() -> None:
    url = os.environ.get("AISEO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis service not configured")
    redis = pytest.importorskip("redis")
    pytest.importorskip("celery")
    from aiseoonline_api.jobs import create_celery_app

    client = redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
    try:
        assert client.ping()
        key = f"aiseoonline:integration:{uuid4().hex}"
        assert client.set(key, "ok", ex=30)
        assert client.get(key) == b"ok"
        client.delete(key)
    finally:
        client.close()

    app = create_celery_app(Settings(_env_file=None, environment="test", redis_url=url))
    result = app.send_task("aiseoonline.ping", args=["integration"])
    assert result.get(timeout=30) == {"status": "ok", "message": "integration"}


@pytest.mark.integration
def test_real_readiness() -> None:
    database = os.environ.get("AISEO_TEST_DATABASE_URL")
    redis_url = os.environ.get("AISEO_TEST_REDIS_URL")
    if not database or not redis_url:
        pytest.skip("Integration storage not configured")
    from fastapi.testclient import TestClient

    settings = Settings(_env_file=None, database_url=database, redis_url=redis_url)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/ready").json() == {
            "status": "ready", "database": "ok", "redis": "ok"
        }
