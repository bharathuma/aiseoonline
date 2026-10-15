"""Three additional deterministic SEO checks using the existing crawler."""

import json
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

from aiseoonline_api.crawler import CrawlSession, UnsafeTarget, normalize_url
from aiseoonline_api.public_tools.checks import ToolReport, make_issue
from aiseoonline_api.seo_core.rules import analyze_page

_SUPPORTED_TYPES = {
    "Article",
    "BlogPosting",
    "NewsArticle",
    "FAQPage",
    "HowTo",
    "Organization",
    "Person",
    "Product",
    "BreadcrumbList",
    "LocalBusiness",
    "Event",
    "Recipe",
    "WebSite",
    "WebPage",
    "VideoObject",
}


def check_redirects(url: str) -> ToolReport:
    trace = CrawlSession(url).inspect_redirects()
    hops = [{"url": hop.url, "status": hop.status, "location": hop.location} for hop in trace.hops]
    issues = []
    count = sum(hop.status in {301, 302, 303, 307, 308} for hop in trace.hops)
    if count >= 2:
        issues.append(
            make_issue(
                "redirect.chain",
                "warning",
                "Multiple redirects were observed.",
                "Link directly to the final destination when possible.",
                f"{count} redirect responses from {trace.requested_url}",
            )
        )
    reasons = {
        "loop": (
            "redirect.loop",
            "A redirect loop was detected.",
            "Remove the circular redirects.",
        ),
        "limit": (
            "redirect.limit",
            "The public redirect limit was reached.",
            "Shorten the chain; only three redirects can be followed.",
        ),
        "blocked_destination": (
            "redirect.blocked",
            "A redirect led outside the permitted origin or to an unsafe URL.",
            "Review the destination manually. This checker did not follow it.",
        ),
    }
    if trace.termination in reasons:
        code, message, correction = reasons[trace.termination]
        issues.append(
            make_issue(
                code,
                "error" if trace.termination != "blocked_destination" else "warning",
                message,
                correction,
                f"Last observed: {trace.final_url}",
            )
        )
    elif trace.final_status is not None and trace.final_status >= 400:
        issues.append(
            make_issue(
                "redirect.http_error",
                "warning",
                "The final page returned an HTTP error.",
                "Confirm that the requested URL exists and is accessible.",
                f"HTTP {trace.final_status} at {trace.final_url}",
            )
        )
    return ToolReport(
        tool="redirects",
        requested_url=trace.requested_url,
        final_url=trace.final_url,
        checked_at=datetime.now(UTC),
        facts={
            "hops": hops,
            "redirect_count": count,
            "final_status": trace.final_status,
            "termination": trace.termination,
            "limitation": "Same-origin public redirects only. No unsafe destination is fetched.",
        },
        issues=issues,
    )


def check_canonical(url: str) -> ToolReport:
    page = CrawlSession(url).fetch_page()
    result = analyze_page(page)
    source = normalize_url(page.final_url).value
    canonical_values: list[dict[str, str | int | None]] = []
    for tag in page.html.canonical_tags:
        raw = tag.href
        resolved: str | None
        try:
            resolved = normalize_url(urljoin(source, raw)).value if raw.strip() else None
        except (UnsafeTarget, ValueError):
            resolved = None
        if resolved is None:
            kind = "invalid"
        elif resolved == source:
            kind = "self-referencing"
        elif urlsplit(raw).scheme not in ("https", "http"):
            kind = "relative"
        elif urlsplit(resolved).hostname != urlsplit(source).hostname:
            kind = "external"
        else:
            kind = "absolute"
        canonical_values.append(
            {
                "raw": raw,
                "resolved": resolved,
                "classification": kind,
                "element": tag.evidence.element,
                "ordinal": tag.evidence.ordinal,
            }
        )
    findings = [
        make_issue(
            finding.rule_id,
            finding.severity,
            finding.summary,
            finding.recommendation,
            "; ".join(
                f"{e.reference.element}#{e.reference.ordinal}: {e.observed[:65]}"
                for e in finding.evidence[:2]
            ),
        )
        for finding in result.findings
        if finding.rule_id.startswith("canonical.")
    ]
    # The underlying rule engine reports cross-domain and invalid declarations.
    # Relative/self-referencing declarations are descriptive, not intrinsically errors.
    return ToolReport(
        tool="canonical",
        requested_url=page.requested_url,
        final_url=page.final_url,
        checked_at=page.captured_at,
        facts={
            "canonical_count": len(canonical_values),
            "declarations": canonical_values,
            "http_status": page.http_status,
            "limitation": "HTML canonicals only; ignores HTTP Link headers and Google selection.",
        },
        issues=findings,
    )


def _deny_constant(value: str) -> None:
    raise ValueError("Nonstandard JSON constant")


def _type_names(value: object) -> list[str]:
    if isinstance(value, str) and value:
        return [value[:100]]
    if isinstance(value, list):
        return [item[:100] for item in value[:20] if isinstance(item, str) and item]
    return []


def check_schema(url: str) -> ToolReport:
    page = CrawlSession(url).fetch_page()
    scripts = page.html.structured_data
    findings = []
    types: set[str] = set()
    parsed_blocks = 0
    entities = 0
    samples: list[dict[str, object]] = []
    if not scripts:
        findings.append(
            make_issue(
                "schema.not_found",
                "info",
                "No JSON-LD blocks were found in the fetched HTML.",
                "Add relevant structured data only if it accurately describes the page.",
                "No script[type=application/ld+json] extracted",
            )
        )
    for script in scripts:
        evidence = f"{script.evidence.element}#{script.evidence.ordinal}"
        try:
            value = json.loads(script.json_text, parse_constant=_deny_constant)
        except (ValueError, RecursionError):
            findings.append(
                make_issue(
                    "schema.invalid_json",
                    "error",
                    "JSON-LD contains invalid JSON.",
                    "Correct the JSON syntax and confirm the markup can be parsed.",
                    evidence,
                )
            )
            continue
        parsed_blocks += 1
        if isinstance(value, dict):
            nodes = value.get("@graph", [value])
            default_context = value.get("@context")
            if not isinstance(nodes, list):
                findings.append(
                    make_issue(
                        "schema.invalid_graph",
                        "warning",
                        "The @graph value should be an array.",
                        "Provide an array of structured-data nodes.",
                        evidence,
                    )
                )
                nodes = []
        elif isinstance(value, list):
            nodes = value
            default_context = None
        else:
            findings.append(
                make_issue(
                    "schema.invalid_root",
                    "warning",
                    "JSON-LD should contain an object or array.",
                    "Use an object with @context and @type, or an array of objects.",
                    evidence,
                )
            )
            continue
        for idx, node in enumerate(nodes[:50]):
            location = f"{evidence} node {idx + 1}"
            if not isinstance(node, dict):
                findings.append(
                    make_issue(
                        "schema.invalid_node",
                        "warning",
                        "A JSON-LD item is not an object.",
                        "Replace the item with a structured-data object.",
                        location,
                    )
                )
                continue
            entities += 1
            context = node.get("@context", default_context)
            if context is None:
                findings.append(
                    make_issue(
                        "schema.context_missing",
                        "warning",
                        "A JSON-LD node lacks @context.",
                        "Declare the intended schema.org context.",
                        location,
                    )
                )
            elif isinstance(context, str) and context.rstrip("/") not in (
                "https://schema.org",
                "http://schema.org",
            ):
                findings.append(
                    make_issue(
                        "schema.context_other",
                        "info",
                        "A non-schema.org context was declared.",
                        "Confirm this context is appropriate for your intended consumer.",
                        location,
                    )
                )
            node_types = _type_names(node.get("@type"))
            if not node_types:
                findings.append(
                    make_issue(
                        "schema.type_missing",
                        "warning",
                        "A JSON-LD node has no usable @type.",
                        "Declare the entity type where applicable.",
                        location,
                    )
                )
            else:
                types.update(node_types)
            if len(samples) < 20:
                samples.append({"evidence": location, "types": node_types})
        if len(nodes) > 50:
            findings.append(
                make_issue(
                    "schema.node_limit",
                    "info",
                    "Only the first 50 nodes per block were inspected.",
                    "Split large graphs and review remaining nodes separately.",
                    evidence,
                )
            )
    return ToolReport(
        tool="schema",
        requested_url=page.requested_url,
        final_url=page.final_url,
        checked_at=page.captured_at,
        facts={
            "jsonld_blocks": len(scripts),
            "parsed_blocks": parsed_blocks,
            "entities": entities,
            "types": sorted(types),
            "recognized_common_types": sorted(types & _SUPPORTED_TYPES),
            "nodes": samples,
            "limitation": "JSON-LD structure only; not a Google rich-result eligibility test.",
        },
        issues=findings[:75],
    )
