"""Controlled fixtures for the first free SEO tools; no external HTTP requests."""

import socket
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, UnsafeTarget, parse_html
from aiseoonline_api.main import create_app
from aiseoonline_api.public_tools import checks, routes


def resource(body: bytes, kind: str = "text/plain", status: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        body=body,
        requested_url="https://example.org/sitemap.xml",
        final_url="https://example.org/sitemap.xml",
        status=status,
        content_type=kind,
        charset="utf-8",
        redirects=(),
    )


def fake_session(
    monkeypatch: pytest.MonkeyPatch, content: bytes, *, mime: str = "text/plain", status: int = 200
) -> None:
    class Session:
        def __init__(self, url: str) -> None:
            self.url = url

        def fetch_resource(self, kind: str) -> SimpleNamespace:
            return resource(content, mime, status)

    monkeypatch.setattr(checks, "CrawlSession", Session)


def test_robots_reports_lines_and_syntax_but_not_claimed_crawler_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_session(
        monkeypatch,
        b"Disallow: /tmp\nUser-agent: *\nDisallow: /private\nBad line\nHost: example.org\n",
    )
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


@pytest.mark.parametrize(
    "xml",
    [
        b"<urlset><url>",
        b"<!DOCTYPE a [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><urlset/>",
        b"<unknown/>",
    ],
)
def test_sitemap_invalid_xml_is_rejected(monkeypatch: pytest.MonkeyPatch, xml: bytes) -> None:
    fake_session(monkeypatch, xml, mime="application/xml")
    with pytest.raises(ValueError):
        checks.check_sitemap("https://example.org/sitemap.xml")


def test_meta_uses_real_snapshot_and_rule_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    html = parse_html(
        b'<html><head><title>Hi</title><meta name="description" '
        b'content="Evidence from fixture"/></head><body><h1>Headline</h1></body></html>',
        "https://example.org/",
    )
    snapshot = PageSnapshot(
        requested_url="https://example.org/",
        final_url="https://example.org/",
        captured_at=datetime.now(UTC),
        http_status=200,
        redirects=(),
        content_bytes=150,
        html=html,
    )

    class Session:
        def __init__(self, url: str) -> None:
            self.url = url

        def fetch_page(self) -> PageSnapshot:
            return snapshot

    monkeypatch.setattr(checks, "CrawlSession", Session)
    result = checks.check_meta("https://example.org/")
    assert result.facts["title"] == "Hi"
    assert result.facts["h1"] == ["Headline"]
    assert any(x.code.startswith("title.") for x in result.issues)
    assert all(x.evidence for x in result.issues)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def allowed(*args: object) -> bool:
        return True

    monkeypatch.setattr(routes, "reserve_budget", allowed)
    return TestClient(create_app(Settings(_env_file=None, environment="test")))


@pytest.mark.parametrize(
    "bad",
    [
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/",
        "file:///etc/passwd",
        "https://example.org:8080/",
        "http://localhost/",
        "https://user:pass@example.org/",
    ],
)
def test_api_rejects_unsafe_urls_before_network(client: TestClient, bad: str) -> None:
    result = client.post("/api/v1/tools/meta", json={"url": bad})
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("path", ["robots", "sitemap", "meta"])
def test_api_exposes_real_typed_routes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    def fake(url: str) -> checks.ToolReport:
        return checks.ToolReport(
            tool=path,
            requested_url=url,
            final_url=url,
            checked_at=datetime.now(UTC),
            facts={"observed": 1},
            issues=[],
        )

    monkeypatch.setattr(
        routes,
        {"robots": "check_robots", "sitemap": "check_sitemap", "meta": "check_meta"}[path],
        fake,
    )
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


class LiveFixture(BaseHTTPRequestHandler):
    robots = b"User-agent: *\nAllow: /\n"
    sitemap = SITEMAP

    def do_GET(self) -> None:
        if self.path == "/robots.txt":
            body, kind = self.robots, "text/plain"
        elif self.path == "/sitemap.xml":
            body, kind = self.sitemap, "application/xml"
        elif self.path == "/page":
            body = (
                b"<html><head><title>Fixture page</title>"
                b'<meta name="description" content="Fixture description"></head>'
                b"<body><h1>Heading</h1></body></html>"
            )
            kind = "text/html"
        elif self.path == "/headings":
            body = (
                b"<html><h2>Second level</h2><h4>Fourth level</h4>"
                b"<h1>Main subject</h1><h2>Details</h2></html>"
            )
            kind = "text/html"
        elif self.path == "/social":
            body = (
                b"<html><head><title>Fallback</title>"
                b'<meta property="og:title" content="OG Fixture">'
                b'<meta property="og:description" content="Actual description">'
                b'<meta property="og:image" content="https://example.org/card.png">'
                b'<meta name="twitter:card" content="summary_large_image">'
                b"</head></html>"
            )
            kind = "text/html"
        elif self.path == "/links":
            body = (
                b'<html><a href="/ok">Valid</a>'
                b'<a href="/missing">Missing</a>'
                b'<a href="/failed-link">Server issue</a>'
                b'<a href="/extra">Beyond budget</a>'
                    b'<a href="https://example.org/secure">Same host, other scheme</a>'
                b'<a href="https://external.org/other">External</a></html>'
            )
            kind = "text/html"
        elif self.path == "/ok":
            body, kind = b"<html><h1>OK</h1></html>", "text/html"
        elif self.path == "/failed-link":
            self.send_response(503)
            self.end_headers()
            return
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def live_site(monkeypatch: pytest.MonkeyPatch) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), LiveFixture)
    server.RequestHandlerClass.robots = b"User-agent: *\nAllow: /\n"
    server.RequestHandlerClass.sitemap = SITEMAP
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def dns(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        assert host == "example.org"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def connect(address: tuple[str, int], **kwargs: object) -> socket.socket:
        assert address[0] == "93.184.216.34"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(float(kwargs.get("timeout", 3)))
        sock.connect(server.server_address)
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(socket, "create_connection", connect)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_three_public_tools_really_fetch_and_parse_local_fixture(
    client: TestClient,
    live_site: ThreadingHTTPServer,
) -> None:
    for path, expected_key, expected in (
        ("robots", "directives", 2),
        ("sitemap", "entries", 3),
        ("meta", "title", "Fixture page"),
    ):
        url = (
            "https://example.org/"
            if path == "robots"
            else ("http://example.org/page" if path == "meta" else "http://example.org/sitemap.xml")
        )
        if path == "robots":
            url = "http://example.org/"
        response = client.post(f"/api/v1/tools/{path}", json={"url": url})
        assert response.status_code == 200, response.text
        assert response.json()["facts"][expected_key] == expected


def test_robot_disallow_rejects_page_without_fetching_it(
    client: TestClient,
    live_site: ThreadingHTTPServer,
) -> None:
    live_site.RequestHandlerClass.robots = b"User-agent: *\nDisallow: /page\n"
    response = client.post("/api/v1/tools/meta", json={"url": "http://example.org/page"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "robots_denied"


def test_oversized_xml_is_rejected_before_parse(
    client: TestClient,
    live_site: ThreadingHTTPServer,
) -> None:
    live_site.RequestHandlerClass.sitemap = b"x" * 525000
    response = client.post("/api/v1/tools/sitemap", json={"url": "http://example.org/sitemap.xml"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "crawl_limit"


@pytest.mark.parametrize(
    ("tool", "path", "expected_key"),
    [
        ("headings", "/headings", "headings"),
        ("links", "/links", "links"),
        ("social", "/social", "open_graph"),
    ],
)
def test_final_tools_fetch_actual_local_html(
    client: TestClient,
    live_site: ThreadingHTTPServer,
    tool: str,
    path: str,
    expected_key: str,
) -> None:
    result = client.post(f"/api/v1/tools/{tool}", json={"url": "http://example.org" + path})
    assert result.status_code == 200, result.text
    assert expected_key in result.json()["facts"]
    assert result.json()["tool"] == tool


def test_heading_outline_has_real_order_and_advisory_jumps(
    client: TestClient,
    live_site: ThreadingHTTPServer,
) -> None:
    result = client.post("/api/v1/tools/headings", json={"url": "http://example.org/headings"})
    assert result.status_code == 200, result.text
    facts = result.json()["facts"]
    assert [h["level"] for h in facts["headings"]] == [2, 4, 1, 2]
    assert facts["counts"]["h1"] == 1
    assert any(i["code"] == "heading.skipped_level" for i in result.json()["issues"])


def test_link_checker_verifies_only_three_same_origin_destinations(
    client: TestClient,
    live_site: ThreadingHTTPServer,
) -> None:
    result = client.post("/api/v1/tools/links", json={"url": "http://example.org/links"})
    assert result.status_code == 200, result.text
    facts = result.json()["facts"]
    assert facts["internal_links"] == 5
    assert facts["external_links"] == 1
    assert facts["probed_destinations"] == 3
    assert facts["verified_broken"] == 1
    records = {item["url"]: item for item in facts["links"]}
    assert records["http://example.org/missing"]["status"] == 404
    assert records["http://example.org/ok"]["status"] == 200
    assert records["https://external.org/other"]["state"] == "not_checked"
    assert records["http://example.org/extra"]["state"] == "not_checked"
    assert records["https://example.org/secure"]["classification"] == "internal"
    assert records["https://example.org/secure"]["state"] == "not_checked"
    assert any(i["code"] == "links.broken_verified" for i in result.json()["issues"])
    assert any(i["code"] == "links.upstream_error" for i in result.json()["issues"])


def test_link_checker_respects_robots_on_probed_target(
    client: TestClient,
    live_site: ThreadingHTTPServer,
) -> None:
    live_site.RequestHandlerClass.robots = b"User-agent: *\nDisallow: /missing\n"
    result = client.post("/api/v1/tools/links", json={"url": "http://example.org/links"})
    assert result.status_code == 200, result.text
    records = {item["url"]: item for item in result.json()["facts"]["links"]}
    assert records["http://example.org/missing"]["state"] == "robots_blocked"
    assert records["http://example.org/missing"]["status"] is None
    assert result.json()["facts"]["verified_broken"] == 0


def test_social_data_and_approximation_are_explicit(
    client: TestClient,
    live_site: ThreadingHTTPServer,
) -> None:
    result = client.post("/api/v1/tools/social", json={"url": "http://example.org/social"})
    assert result.status_code == 200, result.text
    facts = result.json()["facts"]
    assert facts["open_graph"]["og:title"] == ["OG Fixture"]
    assert facts["twitter_x"]["twitter:card"] == ["summary_large_image"]
    assert facts["approximate_preview"]["title"] == "OG Fixture"
    assert "Approximation" in facts["preview_disclaimer"]


@pytest.mark.parametrize("tool", ["headings", "links", "social"])
def test_final_tools_reject_private_urls_before_network(client: TestClient, tool: str) -> None:
    response = client.post(f"/api/v1/tools/{tool}", json={"url": "http://169.254.169.254/latest/"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
