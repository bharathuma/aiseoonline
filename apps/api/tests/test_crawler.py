"""Controlled HTTP fixtures exercise crawler security without external requests."""

import socket
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aiseoonline_api.crawler import (
    CrawlLimitExceeded,
    CrawlLimits,
    CrawlSession,
    CrawlTimeout,
    HttpStatusError,
    InvalidPage,
    RobotsDenied,
    UnsafeTarget,
    normalize_url,
    parse_html,
    resolve_public_addresses,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://public.example.net/",
        "https://127.0.0.1/",
        "http://10.0.0.1/",
        "https://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "https://[::ffff:10.0.0.1]/",
        "https://[::ffff:8.8.8.8]/",
        "http://localhost/",
        "http://router.local/",
        "http://example.invalid/",
        "https://foo.internal/",
        "http://example.com:8080/",
        "https://user:pass@domain.org/",
        "https://user@domain.org/",
        "https://domain.org\\@127.0.0.1/",
        "https://domain.org/\r\nInjected: yes",
        "https://domain.org:abc/",
        "http://256.256.256.256/",
        "http://host_name.example.org/",
        "http://service/",
        "https://[fe80::1%25eth0]/",
    ],
)
def test_rejects_unsafe_url(url: str) -> None:
    with pytest.raises(UnsafeTarget):
        normalize_url(url)


def test_normalization_removes_fragments_and_default_ports() -> None:
    target = normalize_url("HTTPS://Example.ORG:443/path?source=one#fragment")
    assert target.value == "https://example.org/path?source=one"
    assert target.origin == ("https", "example.org", 443)
    assert target.request_target == "/path?source=one"
    assert normalize_url("https://bücher.org/").host == "xn--bcher-kva.org"


def test_dns_blocks_entire_answer_if_any_ip_is_restricted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def lookup(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    with pytest.raises(UnsafeTarget):
        resolve_public_addresses(normalize_url("http://example.org/"))


def test_dns_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow_lookup(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        time.sleep(0.2)
        return []

    monkeypatch.setattr(socket, "getaddrinfo", slow_lookup)
    started = time.monotonic()
    with pytest.raises(CrawlTimeout):
        resolve_public_addresses(normalize_url("http://example.org/"), timeout=0.01)
    assert time.monotonic() - started < 0.15


def test_passive_html_extraction_includes_evidence_and_never_executes_scripts() -> None:
    body = b"""<!doctype html><html><head><title>Example &amp; More</title>
    <meta name="description" content="Summary"/>
    <meta name="robots" content="noindex, nofollow"/>
    <link rel="canonical" href="https://example.org/primary"/>
    <script type="application/ld+json">{"@type":"WebPage"}</script>
    </head><body><h1>Hello</h1><h2>Details</h2><a href="/about">About</a>
    <a href="javascript:alert(1)">Bad</a><script>window.alert(1)</script></body></html>"""
    page = parse_html(body, "https://example.org/")
    assert page.title == "Example & More"
    assert page.title_evidence is not None
    assert page.title_evidence.source_url == "https://example.org/"
    assert page.headings[1].text == "Details"
    assert page.robots == ("noindex", "nofollow")
    assert page.canonical == ("https://example.org/primary",)
    assert page.structured_data[0].json_text == '{"@type":"WebPage"}'
    assert all(not link.href.startswith("javascript:") for link in page.links)


def test_malformed_html_and_invalid_encoding_are_safe() -> None:
    page = parse_html(b"<title>Bad\xff<title><h1>Open", "https://example.org/")
    assert page.encoding_repaired
    assert page.title is None
    other = parse_html(b"<h1>ok</h1>", "https://example.org/", "unsupported-charset")
    assert other.headings[0].text == "ok"


class SiteFixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        requests = self.server.requests  # type: ignore[attr-defined]
        requests.append((self.path, self.headers.get("Host")))
        if self.path == "/robots.txt":
            code = self.server.robots_status  # type: ignore[attr-defined]
            body = self.server.robots_body  # type: ignore[attr-defined]
            self.reply(code, body, "text/plain")
        elif self.path in ("/redirect", "/unsafe", "/offsite", "/loop"):
            location = {
                "/redirect": "/page",
                "/unsafe": "http://169.254.169.254/latest/meta-data/",
                "/offsite": "http://other.example.org/",
                "/loop": "/loop",
            }[self.path]
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()
        elif self.path == "/giant":
            self.reply(200, b"x" * 12000, "text/html", length=False)
        elif self.path == "/huge-length":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", "999999999")
            self.end_headers()
        elif self.path == "/slow":
            time.sleep(0.4)
            self.reply(200, b"<h1>Slow</h1>", "text/html")
        elif self.path == "/invalid-type":
            self.reply(200, b"PNG", "image/png")
        elif self.path == "/broken-charset":
            self.reply(200, b"<title>Bad\xff</title>", "text/html; charset=utf-8")
        elif self.path == "/failed":
            self.reply(503, b"failure", "text/plain")
        elif self.path == "/page":
            self.reply(200, b"<title>Real page</title><h1>Hello</h1>", "text/html")
        else:
            self.reply(404, b"missing", "text/plain")

    def reply(self, status: int, body: bytes, mime: str, *, length: bool = True) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", mime)
            if length:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def site(monkeypatch: pytest.MonkeyPatch) -> Iterator[ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), SiteFixtureHandler)
    server.requests = []  # type: ignore[attr-defined]
    server.dialed = []  # type: ignore[attr-defined]
    server.robots_status = 200  # type: ignore[attr-defined]
    server.robots_body = b"User-agent: *\nAllow: /\n"  # type: ignore[attr-defined]
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def public_dns(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        if host != "example.org":
            raise OSError("Only fixture DNS is available")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def direct_dial(address: tuple[str, int], **kwargs: object) -> socket.socket:
        calls = server.dialed  # type: ignore[attr-defined]
        calls.append(address)
        assert address[0] == "93.184.216.34"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(float(kwargs.get("timeout", 3)))
        sock.connect(server.server_address)
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    monkeypatch.setattr(socket, "create_connection", direct_dial)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def limits(**kwargs: object) -> CrawlLimits:
    options: dict[str, object] = {"min_interval": 0, "total_timeout": 3}
    options.update(kwargs)
    return CrawlLimits(**options)  # type: ignore[arg-type]


def test_fetches_public_html_from_validated_ip(site: ThreadingHTTPServer) -> None:
    page = CrawlSession("http://example.org/page", limits=limits()).fetch_page()
    assert page.html.title == "Real page"
    assert page.html.headings[0].text == "Hello"
    assert page.http_status == 200
    assert page.captured_at.tzinfo is not None
    assert site.dialed == [("93.184.216.34", 80)] * 2  # type: ignore[attr-defined]
    requests = site.requests  # type: ignore[attr-defined]
    assert requests[0] == ("/robots.txt", "example.org")


def test_valid_redirect_is_recorded(site: ThreadingHTTPServer) -> None:
    result = CrawlSession("http://example.org/redirect", limits=limits()).fetch_page()
    assert result.final_url == "http://example.org/page"
    assert result.redirects == ("http://example.org/redirect",)


@pytest.mark.parametrize("path", ["/unsafe", "/offsite"])
def test_unsafe_redirects_never_dial_destination(site: ThreadingHTTPServer, path: str) -> None:
    with pytest.raises(UnsafeTarget):
        CrawlSession("http://example.org" + path, limits=limits()).fetch_page()
    assert len(site.dialed) == 2  # type: ignore[attr-defined]


def test_redirect_loop_is_rejected(site: ThreadingHTTPServer) -> None:
    with pytest.raises(CrawlLimitExceeded):
        CrawlSession("http://example.org/loop", limits=limits()).fetch_page()


def test_robots_disallow_prevents_page_request(site: ThreadingHTTPServer) -> None:
    site.robots_body = b"User-agent: *\nDisallow: /page\n"  # type: ignore[attr-defined]
    with pytest.raises(RobotsDenied):
        CrawlSession("http://example.org/page", limits=limits()).fetch_page()
    assert len(site.dialed) == 1  # type: ignore[attr-defined]


def test_redirect_destination_is_also_subject_to_robots(site: ThreadingHTTPServer) -> None:
    site.robots_body = b"User-agent: *\nDisallow: /page\n"  # type: ignore[attr-defined]
    with pytest.raises(RobotsDenied):
        CrawlSession("http://example.org/redirect", limits=limits()).fetch_page()
    requests = site.requests  # type: ignore[attr-defined]
    assert [path for path, _ in requests] == ["/robots.txt", "/redirect"]


def test_robots_failure_is_fail_closed(site: ThreadingHTTPServer) -> None:
    site.robots_status = 503  # type: ignore[attr-defined]
    with pytest.raises(RobotsDenied):
        CrawlSession("http://example.org/page", limits=limits()).fetch_page()


def test_missing_robots_permits_public_page(site: ThreadingHTTPServer) -> None:
    site.robots_status = 404  # type: ignore[attr-defined]
    page = CrawlSession("http://example.org/page", limits=limits()).fetch_page()
    assert page.html.title == "Real page"


def test_excessive_robots_delay_denies_crawl(site: ThreadingHTTPServer) -> None:
    site.robots_body = b"User-agent: *\nCrawl-delay: 25\n"  # type: ignore[attr-defined]
    with pytest.raises(RobotsDenied):
        CrawlSession("http://example.org/page", limits=limits()).fetch_page()


@pytest.mark.parametrize("path", ["/giant", "/huge-length"])
def test_both_streamed_and_declared_size_limits(site: ThreadingHTTPServer, path: str) -> None:
    with pytest.raises(CrawlLimitExceeded):
        CrawlSession("http://example.org" + path, limits=limits(max_bytes=2048)).fetch_page()


def test_timeout_error_is_bounded(site: ThreadingHTTPServer) -> None:
    with pytest.raises(CrawlTimeout):
        CrawlSession("http://example.org/slow", limits=limits(connect_timeout=0.05)).fetch_page()


def test_non_html_content_is_rejected(site: ThreadingHTTPServer) -> None:
    with pytest.raises(InvalidPage):
        CrawlSession("http://example.org/invalid-type", limits=limits()).fetch_page()


def test_invalid_character_decoding_is_reported(site: ThreadingHTTPServer) -> None:
    page = CrawlSession("http://example.org/broken-charset", limits=limits()).fetch_page()
    assert page.html.encoding_repaired


def test_session_counts_failed_attempts(site: ThreadingHTTPServer) -> None:
    session = CrawlSession("http://example.org/failed", limits=limits())
    with pytest.raises(HttpStatusError) as failure:
        session.fetch_page()
    assert failure.value.status_code == 503
    with pytest.raises(CrawlLimitExceeded):
        session.fetch_page()


def test_unverified_callers_cannot_request_deep_scans() -> None:
    with pytest.raises(ValueError, match="Multi-page"):
        CrawlLimits(max_pages=2)
    with pytest.raises(ValueError):
        CrawlLimits(max_bytes=2_000_000)
    with pytest.raises(ValueError):
        CrawlLimits(max_redirects=10)
