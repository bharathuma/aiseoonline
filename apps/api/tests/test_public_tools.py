"""Controlled fixtures for the first free SEO tools; no external HTTP requests."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, UnsafeTarget, parse_html
from aiseoonline_api.main import create_app
from aiseoonline_api.public_tools import checks, routes


def resource(body: bytes, kind: str = "text/plain", status: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        body=body, requested_url="https://example.org/sitemap.xml",
        final_url="https://example.org/sitemap.xml", status=status,
        content_type=kind, charset="utf-8", redirects=()
    )


def fake_session(monkeypatch: pytest.MonkeyPatch, content: bytes, *,
                 mime: str = "text/plain", status: int = 200) -> None:
    class Session:
        def __init__(self, url: str) -> None:
            self.url = url

        def fetch_resource(self, kind: str) -> SimpleNamespace:
            return resource(content, mime, status)

    monkeypatch.setattr(checks, "CrawlSession", Session)


def test_robots_reports_lines_and_syntax_but_not_claimed_crawler_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session(monkeypatch, b"Disallow: /tmp\nUser-agent: *\nDisallow: /private\nBad line\nHost: example.org\n")
    result = checks.check_robots("https://example.org/")
    assert result.facts["directives"] == 4
    assert result.facts["user_agents"] == ["*"]
    assert "not verified" in result.facts["limitation"]
    assert {"robots.group", "robots.syntax", "robots.extension"} <= {
        entry.code for entry in result.issues
    }


def test_robots_missing_file_is_informational(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session(monkeypatch, b"", status=404)
    report = checks.check_robots("https://example.org/")
    assert report.facts["http_status"] == 404
    assert report.issues[0].severity == "info"


def test_robots_invalid_encoding(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_session(monkeypatch, b"User-agent: *\nDisallow: /\xff")
    assert "robots.encoding" in [x.code for x in checks.check_robots("https://example.org/").issues]


SITEMAP = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://example.org/a</loc></url>
<url><loc>https://example.org/a</loc></url>
<url><loc>javascript:alert(1)</loc></url>
</urlset>"""


def test_sitemap_with_namespace_duplicates_and_invalid_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session(monkeypatch, SITEMAP, mime="application/xml")
    result = checks.check_sitemap("https://example.org/sitemap.xml")
    assert result.facts["kind"] == "urlset"
    assert result.facts["entries"] == 3
    assert result.facts["invalid_entries"] == 1
    assert {"sitemap.duplicate", "sitemap.location"} <= {i.code for i in result.issues}
    assert result.facts["children_fetched"] is False


def test_sitemap_index_is_not_recursively_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    xml = b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://example.org/child.xml</loc></sitemap></sitemapindex>'
    fake_session(monkeypatch, xml, mime="application/xml")
    result = checks.check_sitemap("https://example.org/sitemap.xml")
    assert result.facts["kind"] == "sitemapindex"
    assert result.facts["sample_urls"] == ["https://example.org/child.xml"]
    assert result.facts["children_fetched"] is False


@pytest.mark.parametrize("xml", [
    b"<urlset><url>",
    b"<!DOCTYPE a [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><urlset/>",
    b"<unknown/>",
])
def test_sitemap_invalid_xml_is_rejected(monkeypatch: pytest.MonkeyPatch, xml: bytes) -> None:
    fake_session(monkeypatch, xml, mime="application/xml")
    with pytest.raises(ValueError):
        checks.check_sitemap("https://example.org/sitemap.xml")


def test_meta_uses_real_snapshot_and_rule_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    html = parse_html(
        b'<html><head><title>Real test title</title><meta name="description" '
        b'content="Evidence from fixture"/></head><body><h1>Headline</h1></body></html>',
        "https://example.org/"
    )
    snapshot = PageSnapshot(
        requested_url="https://example.org/", final_url="https://example.org/",
        captured_at=datetime.now(UTC), http_status=200, redirects=(),
        content_bytes=150, html=html,
    )

    class Session:
        def __init__(self, url: str) -> None:
            self.url = url

        def fetch_page(self) -> PageSnapshot:
            return snapshot

    monkeypatch.setattr(checks, "CrawlSession", Session)
    result = checks.check_meta("https://example.org/")
    assert result.facts["title"] == "Real test title"
    assert result.facts["h1"] == ["Headline"]
    assert any(x.code.startswith("title.") for x in result.issues)
    assert all(x.evidence for x in result.issues)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def allowed(*args: object) -> bool:
        return True

    monkeypatch.setattr(routes, "reserve_budget", allowed)
    return TestClient(create_app(Settings(_env_file=None, environment="test")))


@pytest.mark.parametrize("bad", [
    "http://127.0.0.1/", "http://169.254.169.254/latest/",
    "file:///etc/passwd", "https://example.org:8080/", "http://localhost/",
    "https://user:pass@example.org/"
])
def test_api_rejects_unsafe_urls_before_network(client: TestClient, bad: str) -> None:
    result = client.post("/api/v1/tools/meta", json={"url": bad})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("path", ["robots", "sitemap", "meta"])
def test_api_exposes_real_typed_routes(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                      path: str) -> None:
    fake = lambda url: checks.ToolReport(
        tool=path, requested_url=url, final_url=url,
        checked_at=datetime.now(UTC), facts={"observed": 1}, issues=[]
    )
    monkeypatch.setattr(routes, {"robots": "check_robots", "sitemap": "check_sitemap",
                                 "meta": "check_meta"}[path], fake)
    result = client.post(f"/api/v1/tools/{path}", json={"url": "https://example.org/"})
    assert result.status_code == 200
    assert result.json()["facts"] == {"observed": 1}
    assert result.json()["tool"] == path


def test_api_fails_closed_when_budget_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unavailable(*args: object) -> None:
        return None

    monkeypatch.setattr(routes, "reserve_budget", unavailable)
    client = TestClient(create_app(Settings(_env_file=None, environment="test")))
    result = client.post("/api/v1/tools/robots", json={"url": "https://example.org/"})
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "service_unavailable"


def test_rate_limit_produces_429_and_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def denied(*args: object) -> bool:
        return False

    monkeypatch.setattr(routes, "reserve_budget", denied)
    client = TestClient(create_app(Settings(_env_file=None, environment="test")))
    result = client.post("/api/v1/tools/robots", json={"url": "https://example.org/"})
    assert result.status_code == 429
    assert result.headers["retry-after"] == "3600"


def test_ssrf_fails_at_url_parser_before_any_transport() -> None:
    with pytest.raises(UnsafeTarget):
        from aiseoonline_api.crawler import normalize_url
        normalize_url("http://10.0.0.4/")
