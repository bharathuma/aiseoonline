"""Evidence-based, bounded SEO checks. No model calls or follow-up crawling."""

import re
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from aiseoonline_api.crawler import CrawlSession
from aiseoonline_api.seo_core.rules import analyze_page

NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


class ToolIssue(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    recommendation: str
    evidence: str = Field(max_length=250)


class ToolReport(BaseModel):
    tool: Literal["robots", "sitemap", "meta", "redirects", "canonical", "schema", "headings", "links", "social"]
    requested_url: str
    final_url: str
    checked_at: datetime
    facts: dict[str, Any]
    issues: list[ToolIssue]


def make_issue(
    code: str,
    severity: Literal["error", "warning", "info"],
    message: str,
    recommendation: str,
    evidence: str,
) -> ToolIssue:
    return ToolIssue(
        code=code,
        severity=severity,
        message=message,
        recommendation=recommendation,
        evidence=evidence[:250],
    )


def check_robots(url: str) -> ToolReport:
    doc = CrawlSession(url).fetch_resource("robots")
    warnings: list[ToolIssue] = []
    if doc.status in (404, 410):
        lines: list[str] = []
        warnings.append(
            make_issue(
                "robots.not_found",
                "info",
                "Robots.txt not found.",
                "A robots.txt file is only needed to declare crawler instructions.",
                f"HTTP {doc.status} at {doc.final_url}",
            )
        )
    else:
        if doc.content_type != "text/plain":
            warnings.append(
                make_issue(
                    "robots.mime",
                    "warning",
                    "Unexpected content type.",
                    "Serve robots.txt as text/plain.",
                    doc.content_type,
                )
            )
        text = doc.body.decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        if "�" in text:
            warnings.append(
                make_issue(
                    "robots.encoding",
                    "warning",
                    "Invalid UTF-8 bytes detected.",
                    "Save robots.txt as UTF-8.",
                    "Replacement characters in response",
                )
            )
    agents: list[str] = []
    rules = 0
    has_group = False
    standard = {"user-agent", "allow", "disallow", "sitemap", "crawl-delay"}
    extensions = {"host", "clean-param", "request-rate", "noindex"}
    for number, line in enumerate(lines[:1500], 1):
        entry = line.split("#", 1)[0].strip()
        if not entry:
            continue
        if ":" not in entry:
            warnings.append(
                make_issue(
                    "robots.syntax",
                    "warning",
                    "Missing directive colon.",
                    "Use Directive: value.",
                    f"Line {number}: {entry[:120]}",
                )
            )
            continue
        key, value = (s.strip() for s in entry.split(":", 1))
        low = key.lower()
        rules += 1
        if low == "user-agent":
            has_group = True
            if value:
                agents.append(value[:80])
            else:
                warnings.append(
                    make_issue(
                        "robots.agent",
                        "warning",
                        "Empty User-agent token.",
                        "Specify a crawler token, such as *.",
                        f"Line {number}",
                    )
                )
        elif low in {"allow", "disallow", "crawl-delay"} and not has_group:
            warnings.append(
                make_issue(
                    "robots.group",
                    "warning",
                    "Directive before User-agent.",
                    "Put crawler rules under a User-agent group.",
                    f"Line {number}: {key}",
                )
            )
        if low not in standard:
            warnings.append(
                make_issue(
                    "robots.extension" if low in extensions else "robots.unknown",
                    "info",
                    "Directive support depends on the target crawler.",
                    "Check the crawler's own documentation.",
                    f"Line {number}: {key[:80]}",
                )
            )
        if low == "crawl-delay" and value:
            try:
                delay = float(value)
                if not 0 <= delay <= 86400:
                    raise ValueError
            except ValueError:
                warnings.append(
                    make_issue(
                        "robots.delay",
                        "warning",
                        "Invalid Crawl-delay value.",
                        "Use a nonnegative duration where supported.",
                        f"Line {number}: {value[:80]}",
                    )
                )
    if len(lines) > 1500:
        warnings.append(
            make_issue(
                "robots.limit",
                "warning",
                "Only 1,500 lines reviewed.",
                "Inspect the remaining lines separately.",
                f"{len(lines)} lines",
            )
        )
    return ToolReport(
        tool="robots",
        requested_url=doc.requested_url,
        final_url=doc.final_url,
        checked_at=datetime.now(UTC),
        issues=warnings[:40],
        facts={
            "http_status": doc.status,
            "lines": len(lines),
            "directives": rules,
            "user_agents": list(dict.fromkeys(agents))[:30],
            "limitation": "Syntax review only; crawler behavior was not verified.",
        },
    )


def _parts(tag: str) -> tuple[str, str]:
    if tag.startswith("{"):
        namespace, _, name = tag[1:].partition("}")
        return namespace, name
    return "", tag


def _absolute_url(value: str) -> bool:
    if not value or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return False
    try:
        parts = urlsplit(value)
        return (
            parts.scheme.lower() in ("http", "https")
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and not parts.fragment
        )
    except ValueError:
        return False


def check_sitemap(url: str) -> ToolReport:
    doc = CrawlSession(url).fetch_resource("sitemap")
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", doc.body, re.IGNORECASE):
        raise ValueError("DTD and entities are not permitted")
    try:
        root = ET.fromstring(doc.body)
    except ET.ParseError as exc:
        raise ValueError("Malformed sitemap XML") from exc
    ns, root_name = _parts(root.tag)
    if root_name not in ("urlset", "sitemapindex"):
        raise ValueError("Unsupported sitemap root")
    warnings: list[ToolIssue] = []
    if ns != NAMESPACE:
        warnings.append(
            make_issue(
                "sitemap.namespace",
                "warning",
                "Unexpected sitemap namespace.",
                "Use the standard sitemap namespace.",
                ns or "(none)",
            )
        )
    entries = list(root)
    expected = "url" if root_name == "urlset" else "sitemap"
    seen: set[str] = set()
    locations: list[str] = []
    invalid = 0
    for i, entry in enumerate(entries[:1500], 1):
        if _parts(entry.tag) != (ns, expected):
            invalid += 1
            warnings.append(
                make_issue(
                    "sitemap.element",
                    "warning",
                    "Unexpected sitemap element.",
                    f"Use {expected} elements.",
                    f"Entry {i}: {_parts(entry.tag)[1][:100]}",
                )
            )
            continue
        locs = [(e.text or "").strip() for e in entry if _parts(e.tag) == (ns, "loc")]
        if len(locs) != 1 or not _absolute_url(locs[0]):
            invalid += 1
            warnings.append(
                make_issue(
                    "sitemap.location",
                    "warning",
                    "Entry has no valid absolute HTTP(S) loc.",
                    "Include one absolute loc URL.",
                    f"Entry {i}: {(locs[0] if locs else '(missing)')[:120]}",
                )
            )
            continue
        if locs[0] in seen:
            warnings.append(
                make_issue(
                    "sitemap.duplicate",
                    "warning",
                    "Duplicate URL.",
                    "Remove duplicate entries.",
                    f"Entry {i}: {locs[0][:120]}",
                )
            )
        seen.add(locs[0])
        locations.append(locs[0])
    if len(entries) > 1500:
        warnings.append(
            make_issue(
                "sitemap.limit",
                "warning",
                "Not all entries were inspected.",
                "Split large sitemaps for individual checks.",
                f"{len(entries)} elements",
            )
        )
    return ToolReport(
        tool="sitemap",
        requested_url=doc.requested_url,
        final_url=doc.final_url,
        checked_at=datetime.now(UTC),
        issues=warnings[:40],
        facts={
            "kind": root_name,
            "namespace": ns,
            "entries": len(entries),
            "checked_entries": min(1500, len(entries)),
            "invalid_entries": invalid,
            "sample_urls": locations[:20],
            "children_fetched": False,
        },
    )


def check_meta(url: str) -> ToolReport:
    page = CrawlSession(url).fetch_page()
    report = analyze_page(page)
    html = page.html
    prefixes = ("title.", "description.", "heading.", "canonical.", "robots.")
    findings = [
        make_issue(
            f.rule_id,
            f.severity,
            f.summary,
            f.recommendation,
            "; ".join(
                f"{v.reference.element}#{v.reference.ordinal}: {v.observed[:65]}"
                for v in f.evidence[:2]
            ),
        )
        for f in report.findings
        if f.rule_id.startswith(prefixes)
    ]
    return ToolReport(
        tool="meta",
        requested_url=page.requested_url,
        final_url=page.final_url,
        checked_at=page.captured_at,
        issues=findings[:75],
        facts={
            "http_status": page.http_status,
            "title": html.title,
            "descriptions": [m.content for m in html.meta if m.name.lower() == "description"][:5],
            "h1": [h.text for h in html.headings if h.level == 1][:10],
            "canonicals": list(html.canonical)[:10],
            "robots": list(html.robots)[:20],
            "redirects": list(page.redirects),
            "encoding_repaired": html.encoding_repaired,
        },
    )
