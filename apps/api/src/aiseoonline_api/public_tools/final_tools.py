"""Deterministic heading, internal link and social metadata checks."""

from urllib.parse import urlsplit

from aiseoonline_api.crawler import CrawlLimits, CrawlSession, UnsafeTarget, normalize_url
from aiseoonline_api.crawler.html import MetaTag
from aiseoonline_api.public_tools.checks import ToolReport, make_issue
from aiseoonline_api.seo_core.rules import analyze_page

_MAX_LINK_PROBES = 3


def check_headings(url: str) -> ToolReport:
    """Report the actual document order, without assuming one H1 is mandatory."""
    page = CrawlSession(url).fetch_page()
    headings = [
        {"level": entry.level, "text": entry.text,
         "element": entry.evidence.element, "ordinal": entry.evidence.ordinal}
        for entry in page.html.headings
    ]
    rules = analyze_page(page)
    issues = [
        make_issue(f.rule_id, f.severity, f.summary, f.recommendation,
                   "; ".join(
                       f"{ev.reference.element}#{ev.reference.ordinal}: {ev.observed[:70]}"
                       for ev in f.evidence[:2]
                   ))
        for f in rules.findings if f.rule_id.startswith("heading.")
    ]
    if not headings:
        issues.append(make_issue(
            "heading.none", "info", "No HTML heading elements were captured.",
            "Add meaningful headings where they help readers navigate the page.",
            "No h1-h6 elements were extracted from the fetched HTML",
        ))
    return ToolReport(
        tool="headings", requested_url=page.requested_url, final_url=page.final_url,
        checked_at=page.captured_at, issues=issues[:75],
        facts={
            "headings": headings, "counts": {f"h{n}": sum(h["level"] == n for h in headings)
                                          for n in range(1, 7)},
            "total": len(headings), "http_status": page.http_status,
            "limitation": "Heading structure is advisory. Multiple H1 elements can be valid.",
        },
    )


def check_links(url: str) -> ToolReport:
    """Classify extracted anchors; probe only three selected same-origin URLs."""
    session = CrawlSession(
        url, limits=CrawlLimits(total_timeout=6, min_interval=0.05)
    )
    page = session.fetch_page()
    source = normalize_url(page.final_url)
    observed: list[dict[str, object]] = []
    chosen: list[str] = []
    internal_count = 0
    external_count = 0
    seen: set[str] = set()
    for entry in page.html.links:
        try:
            normalized = normalize_url(entry.href)
        except (UnsafeTarget, ValueError):
            continue
        internal = normalized.origin == source.origin
        if internal:
            internal_count += 1
        else:
            external_count += 1
        if normalized.value in seen:
            continue
        seen.add(normalized.value)
        if len(observed) < 45:
            observed.append({
                "url": normalized.value, "text": entry.text,
                "classification": "internal" if internal else "external",
                "evidence": f"{entry.evidence.element}#{entry.evidence.ordinal}",
                "status": page.http_status if normalized.value == source.value else None,
                "state": "verified" if normalized.value == source.value else "not_checked",
            })
        if (internal and normalized.value != source.value and len(chosen) < _MAX_LINK_PROBES
                and len(observed) <= 45):
            chosen.append(normalized.value)
    probes = {item.url: item for item in session.probe_same_origin_links(tuple(chosen))}
    issues = []
    broken = 0
    for row in observed:
        target = str(row["url"])
        if target not in probes:
            continue
        probe = probes[target]
        row["state"] = probe.state
        row["status"] = probe.status
        if probe.final_url is not None:
            row["final_url"] = probe.final_url
        if probe.state == "verified" and probe.status in (404, 410):
            broken += 1
            issues.append(make_issue(
                "links.broken_verified", "error", "An internal URL returned a broken-page status.",
                "Update the link to a working destination or remove it.",
                f"{row['evidence']}: HTTP {probe.status} {target[:140]}",
            ))
        elif probe.state == "verified" and probe.status is not None and probe.status >= 500:
            issues.append(make_issue(
                "links.upstream_error", "warning", "An internal URL returned a server error.",
                "Investigate the server response; a temporary failure is not proof of a broken link.",
                f"{row['evidence']}: HTTP {probe.status} {target[:140]}",
            ))
    if internal_count == 0:
        issues.append(make_issue(
            "links.none", "info", "No internal links were detected in the fetched HTML.",
            "Review whether contextual links could improve navigation.",
            "No same-origin anchor links captured",
        ))
    return ToolReport(
        tool="links", requested_url=page.requested_url, final_url=page.final_url,
        checked_at=page.captured_at, issues=issues[:40],
        facts={
            "internal_links": internal_count, "external_links": external_count,
            "distinct_links": len(seen), "verified_broken": broken,
            "probed_destinations": len(probes), "max_probes": _MAX_LINK_PROBES,
            "links": observed,
            "limitation": "Only up to three same-origin link destinations are probed. "
                          "Unknown status means unverified, not working or broken. "
                          "External URLs are never probed.",
        },
    )


def _metadata_values(page_meta: tuple[MetaTag, ...]) -> dict[str, list[str]]:
    # ParsedHtml.meta is already bounded by the secure HTML extractor.
    entries: dict[str, list[str]] = {}
    for tag in page_meta:
        name = tag.name.casefold().strip()
        if name.startswith("og:") or name.startswith("twitter:"):
            entries.setdefault(name, []).append(tag.content)
    return entries


def check_social(url: str) -> ToolReport:
    """Extract OG/X tags and offer a plainly approximate social preview."""
    page = CrawlSession(url).fetch_page()
    tags = _metadata_values(page.html.meta)
    og = {key: values[:5] for key, values in tags.items() if key.startswith("og:")}
    twitter = {key: values[:5] for key, values in tags.items()
               if key.startswith("twitter:")}
    findings = []
    for field in ("og:title", "og:description", "og:image"):
        if not any(item.strip() for item in tags.get(field, [])):
            findings.append(make_issue(
                "social.missing_" + field.replace(":", "_"), "info",
                f"No {field} value was extracted.",
                "Add this field if it improves the appearance of shared links.",
                f"No nonempty meta[property={field}] in HTML",
            ))
    for key, values in tags.items():
        distinct = {v.strip() for v in values if v.strip()}
        if len(distinct) > 1:
            findings.append(make_issue(
                "social.conflicting", "warning", f"Conflicting values for {key}.",
                "Use an unambiguous value for this social metadata field.",
                f"{key}: {len(values)} declarations",
            ))
    title = (tags.get("og:title") or tags.get("twitter:title") or
             ([page.html.title] if page.html.title else []))
    description = (tags.get("og:description") or tags.get("twitter:description") or [])
    image = (tags.get("og:image") or tags.get("twitter:image") or [])
    if not tags:
        findings.append(make_issue(
            "social.none", "info", "No Open Graph or X card fields were extracted.",
            "Add relevant social tags only if they support your intended sharing experience.",
            "No og:* or twitter:* metadata in the fetched HTML",
        ))
    return ToolReport(
        tool="social", requested_url=page.requested_url,
        final_url=page.final_url, checked_at=page.captured_at,
        facts={
            "open_graph": og, "twitter_x": twitter, "tag_count": sum(map(len, tags.values())),
            "approximate_preview": {
                "title": title[0] if title else None,
                "description": description[0] if description else None,
                "image_url": image[0] if image else None,
                "site_name": (tags.get("og:site_name") or [urlsplit(page.final_url).hostname])[0],
            },
            "preview_disclaimer": "Approximation only. Platforms may choose different text, "
                                  "image crops, and cached previews. Images are not fetched.",
        },
        issues=findings[:50],
    )
