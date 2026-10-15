"""Executable release-contract checks; never call a paid provider or public website.

These checks prove route and published-fixture invariants in isolated settings.
They do not certify production infrastructure or release readiness.
"""

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from aiseoonline_api.config import Settings
from aiseoonline_api.main import create_app

_REPO = Path(__file__).resolve().parents[3]
_PUBLIC = frozenset(
    {
        "/api/v1/tools/robots",
        "/api/v1/tools/sitemap",
        "/api/v1/tools/meta",
        "/api/v1/tools/redirects",
        "/api/v1/tools/canonical",
        "/api/v1/tools/schema",
        "/api/v1/tools/headings",
        "/api/v1/tools/links",
        "/api/v1/tools/social",
        "/api/v1/tools/ai-meta",
    }
)


def _production() -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://qa:qa@localhost:5432/qa",
        redis_url="redis://localhost:6379/0",
        auth_registration_enabled=False,
        audit_jobs_enabled=False,
        rag_chat_enabled=False,
        analytics_enabled=False,
    )


def test_production_routes_have_all_ten_public_tools_without_private_ai() -> None:
    app = create_app(_production())
    with TestClient(app) as client:
        response = client.get("/api/v1/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
        assert _PUBLIC <= paths.keys()
        assert all("post" in paths[path] for path in _PUBLIC)
        # These are intentionally development-only routes, not feature flags to bypass.
        assert not any(path.startswith("/api/v1/internal/") for path in paths)
        assert not any("rag/chat" in path or "rag-chat" in path for path in paths)
        for url in ("/api/v1/internal/audits", "/api/v1/rag/chat"):
            assert client.post(url, json={}).status_code == 404
        assert client.get("/api/v1/account/projects").status_code == 401


def test_prod_rejects_public_self_signup_without_sensitive_errors() -> None:
    app = create_app(_production())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/account/register",
            headers={"Origin": "https://aiseoonline.com"},
            json={"email": "fixture@example.org", "password": "no-real-password-1234"},
        )
        assert response.status_code == 404
        assert "password" not in response.text.lower()
        assert response.headers["cache-control"] == "no-store"


def test_cloud_metadata_address_is_rejected_before_any_fetch() -> None:
    app = create_app(Settings(_env_file=None, environment="test", redis_url=None))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tools/meta",
            json={"url": "http://169.254.169.254/latest/meta-data"},
        )
        assert response.status_code == 422
        assert response.headers["x-content-type-options"] == "nosniff"


def test_public_evaluation_reports_known_failure_and_real_provenance() -> None:
    fixture = _REPO / "apps/api/evaluations/fixtures/seo-v1.json"
    report_path = _REPO / "apps/web/src/data/benchmarks.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dataset_sha256"] == hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert report["case_count"] == 18
    assert report["paid_calls"] == 0
    assert len(report["cases"]) == report["case_count"]
    misses = [item for item in report["cases"] if not item["matched_expectation"]]
    assert len(misses) == 1
    assert misses[0]["id"] == "rag-semantic-overclaim"
    assert misses[0]["expected"] == "rejected"
    assert misses[0]["observed"] == "accepted"
