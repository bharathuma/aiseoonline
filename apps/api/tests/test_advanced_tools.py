"""Contract and edge-case tests for deterministic public SEO utilities."""

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, RobotsDenied, parse_html
from aiseoonline_api.main import create_app
from aiseoonline_api.public_tools import advanced, routes


def snapshot(body: bytes, url: str = "https://example.org/page") -> PageSnapshot:
    return PageSnapshot(
        requested_url=url,
        final_url=url,
        captured_at=datetime(2026, 10, 15, tzinfo=UTC),
        http_status=200,
        redirects=(),
        content_bytes=len(body),
        html=parse_html(body, url),
    )


def page_fixture(monkeypatch: pytest.MonkeyPatch, html: bytes) -> None:
    page = snapshot(html)

    class FakeSession:
        def __init__(self, url: str) -> None:
            self.url = url

        def fetch_page(self) -> PageSnapshot:
            return page

    monkeypatch.setattr(advanced, "CrawlSession", FakeSession)


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        (b'<link rel="canonical" href="/page">', "self-referencing"),
        (b'<link rel="canonical" href="/different">', "relative"),
        (b'<link rel="canonical" href="https://another.org/page">', "external"),
        (b'<link rel="canonical" href="https://example.org/primary">', "absolute"),
        (b'<link rel="canonical" href="javascript:alert(1)">', "invalid"),
    ],
)
def test_canonical_classifies_from_actual_html(
    monkeypatch: pytest.MonkeyPatch, markup: bytes, expected: str,
) -> None:
    page_fixture(monkeypatch, b"<html><head>" + markup + b"</head></html>")
    result = advanced.check_canonical("https://example.org/page")
    assert result.facts["canonical_count"] == 1
    assert result.facts["declarations"][0]["classification"] == expected
    assert result.facts["declarations"][0]["element"] == "link[rel=canonical]"


def test_canonical_missing_conflicting_and_repeated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_fixture(monkeypatch, b"<html><head></head></html>")
    assert "canonical.missing" in {
        issue.code for issue in advanced.check_canonical("https://example.org/page").issues
    }
    page_fixture(monkeypatch, b'<link rel="canonical" href="/one"><link rel="canonical" href="/two">')
    report = advanced.check_canonical("https://example.org/page")
    assert "canonical.conflicting" in {issue.code for issue in report.issues}
    assert len(report.facts["declarations"]) == 2


def test_canonical_does_not_fetch_declared_external_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_fixture(monkeypatch, b'<link rel="canonical" href="https://another.org/page">')
    report = advanced.check_canonical("https://example.org/page")
    assert report.facts["declarations"][0]["resolved"] == "https://another.org/page"
    assert report.facts["http_status"] == 200


def test_schema_parses_graph_and_labels_supported_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markup = (
        b'<script type="application/ld+json">'
        b'{"@context":"https://schema.org","@graph":['
        b'{"@type":"Article","headline":"A"},'
        b'{"@type":["Person","CustomType"],"name":"B"}]}</script>'
    )
    page_fixture(monkeypatch, markup)
    result = advanced.check_schema("https://example.org/page")
    assert result.facts["parsed_blocks"] == 1
    assert result.facts["entities"] == 2
    assert "Article" in result.facts["recognized_common_types"]
    assert "CustomType" in result.facts["types"]
    assert not result.issues


@pytest.mark.parametrize(
    ("markup", "code"),
    [
        (b'<script type="application/ld+json">{broken}</script>', "schema.invalid_json"),
        (b'<script type="application/ld+json">{"@type":"Product"}</script>',
         "schema.context_missing"),
        (b'<script type="application/ld+json">{"@context":"https://schema.org"}</script>',
         "schema.type_missing"),
        (b'<script type="application/ld+json">{"@graph":"invalid"}</script>',
         "schema.invalid_graph"),
        (b'<script type="application/ld+json">"text"</script>', "schema.invalid_root"),
        (b'<script type="application/ld+json">{"@type":NaN}</script>',
         "schema.invalid_json"),
    ],
)
def test_schema_structural_errors_are_grounded_and_safe(
    monkeypatch: pytest.MonkeyPatch, markup: bytes, code: str,
) -> None:
    page_fixture(monkeypatch, markup)
    result = advanced.check_schema("https://example.org/page")
    assert code in {issue.code for issue in result.issues}
    assert all(issue.evidence for issue in result.issues)


def test_schema_missing_jsonld_is_not_claimed_to_be_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_fixture(monkeypatch, b"<html><head><title>Hi</title></head></html>")
    result = advanced.check_schema("https://example.org/page")
    assert result.issues[0].severity == "info"
    assert result.facts["jsonld_blocks"] == 0


def test_schema_does_not_execute_untrusted_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_fixture(
        monkeypatch,
        b'<script type="application/ld+json">'
        b'{"@context":"https://schema.org","@type":"WebPage",'
        b'"name":"<script>alert(1)</script>"}'
        b"</script>",
    )
    # The untrusted string is data; no scripts are executed by the checker.
    result = advanced.check_schema("https://example.org/page")
    assert result.tool == "schema"
    assert result.facts["parsed_blocks"] == 1


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def allow(*args: Any) -> bool:
        return True

    monkeypatch.setattr(routes, "reserve_budget", allow)
    return TestClient(create_app(Settings(_env_file=None, environment="test")))


@pytest.mark.parametrize("kind", ["redirects", "canonical", "schema"])
def test_new_routes_are_documented_and_typed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    def fake(url: str) -> advanced.ToolReport:
        return advanced.ToolReport(
            tool=kind, requested_url=url, final_url=url,
            checked_at=datetime.now(UTC), facts={"verified": True}, issues=[],
        )

    monkeypatch.setattr(routes, f"check_{kind}", fake)
    result = client.post(f"/api/v1/tools/{kind}", json={"url": "https://example.org/"})
    assert result.status_code == 200
    assert result.json()["tool"] == kind
    assert result.json()["facts"]["verified"] is True
    schema = client.get("/api/v1/openapi.json").json()
    assert f"/api/v1/tools/{kind}" in schema["paths"]


@pytest.mark.parametrize("kind", ["redirects", "canonical", "schema"])
def test_new_routes_reject_private_hosts(client: TestClient, kind: str) -> None:
    response = client.post(
        f"/api/v1/tools/{kind}", json={"url": "http://169.254.169.254/latest"}
    )
    assert response.status_code == 422


def test_new_tool_obeys_robots_denial(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(url: str) -> advanced.ToolReport:
        raise RobotsDenied("No crawling")

    monkeypatch.setattr(routes, "check_schema", denied)
    result = client.post("/api/v1/tools/schema", json={"url": "https://example.org/"})
    assert result.status_code == 403
    assert result.json()["error"]["code"] == "robots_denied"
