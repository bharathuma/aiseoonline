"""Privacy-safe aggregate analytics stays disabled until explicitly activated."""

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from aiseoonline_api.analytics import PUBLIC_PATHS
from aiseoonline_api.config import Settings
from aiseoonline_api.main import create_app


def test_analytics_returns_not_found_by_default() -> None:
    app = create_app(Settings(_env_file=None, environment="test"))
    with TestClient(app) as client:
        result = client.post("/api/v1/analytics/pageview", json={"path": "/tools/"})
    assert result.status_code == 404


def test_analytics_never_accepts_private_paths_or_querystrings() -> None:
    app = create_app(
        Settings(_env_file=None, environment="test", redis_url=None, analytics_enabled=True)
    )
    for invalid in [
        "/internal/audit/",
        "/api/docs",
        "/tools/?token=secret",
        "/unknown/",
        "//evil.example/",
    ]:
        with TestClient(app) as client:
            result = client.post("/api/v1/analytics/pageview", json={"path": invalid})
        assert result.status_code == 422
    assert "/tools/meta-tag-checker/" in PUBLIC_PATHS
    assert "/internal/audit/" not in PUBLIC_PATHS


def test_enabled_analytics_records_only_aggregate_paths() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        redis_url="redis://localhost:6379/0",
        analytics_enabled=True,
    )
    app = create_app(settings)
    session = MagicMock()
    session.eval.return_value = 1
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    with patch("aiseoonline_api.analytics.Redis.from_url", return_value=session) as factory:
        with TestClient(app) as client:
            response = client.post("/api/v1/analytics/pageview", json={"path": "/tools/"})
        assert response.status_code == 204
        assert response.headers["cache-control"] == "no-store"
        _, key_count, aggregate_key, cap = session.eval.call_args.args
        assert key_count == 1 and cap == 10000
        assert aggregate_key.endswith(":/tools/")
        assert "127.0.0.1" not in aggregate_key
        assert factory.called


def test_disabled_storage_and_quota_fail_clearly() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        redis_url="redis://localhost:6379/0",
        analytics_enabled=True,
    )
    app = create_app(settings)
    conn = MagicMock()
    conn.eval.return_value = 0
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    with patch("aiseoonline_api.analytics.Redis.from_url", return_value=conn):
        with TestClient(app) as client:
            result = client.post("/api/v1/analytics/pageview", json={"path": "/"})
        assert result.status_code == 429
    app = create_app(
        Settings(_env_file=None, environment="test", redis_url=None, analytics_enabled=True)
    )
    with TestClient(app) as client:
        result = client.post("/api/v1/analytics/pageview", json={"path": "/"})
    assert result.status_code == 503
