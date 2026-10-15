"""Deterministic, evidence-first checks. No model or network calls."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from aiseoonline_api.crawler.html import Evidence, MetaTag
from aiseoonline_api.crawler.service import PageSnapshot
from aiseoonline_api.crawler.urls import UnsafeTarget, normalize_url

from .models import AnalysisReport, FindingEvidence, SeoFinding, Severity


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """Advisory thresholds; neither a search-engine standard nor a ranking promise."""

    title_min_chars: int = 15
    title_max_chars: int = 65
    description_min_chars: int = 50
    description_max_chars: int = 160

    def __post_init__(self) -> None:
        if not (1 <= self.title_min_chars < self.title_max_chars <= 500):
            raise ValueError("Invalid title advisory range")
        if not (1 <= self.description_min_chars < self.description_max_chars <= 1000):
            raise ValueError("Invalid description advisory range")


def _ev(url: str, element: str, observed: str, ordinal: int = 1) -> FindingEvidence:
    return FindingEvidence(Evidence(url, element, ordinal), observed[:180])


def _tag_ev(tag: MetaTag) -> FindingEvidence:
    return FindingEvidence(tag.evidence, tag.content[:180])


def _add(
    result: list[SeoFinding],
    url: str,
    code: str,
    severity: Severity,
    summary: str,
    explanation: str,
    fix: str,
    evidence: tuple[FindingEvidence, ...],
) -> None:
    result.append(SeoFinding(code, severity, url, summary, explanation, fix, evidence))


def _norm(raw: str, base: str) -> str | None:
    try:
        return normalize_url(urljoin(base, raw)).value
    except (UnsafeTarget, ValueError):
        return None


def _html_findings(snapshot: PageSnapshot, conf: RuleConfig) -> list[SeoFinding]:
    url, html = snapshot.final_url, snapshot.html
    found: list[SeoFinding] = []
    title = html.title or ""
    title_ref = (
        FindingEvidence(html.title_evidence, title[:180])
        if html.title_evidence is not None
        else _ev(url, "document", "No title was extracted")
    )
    if not title.strip():
        _add(
            found,
            url,
            "title.missing",
            "error",
            "Missing page title",
            "No nonempty HTML title was extracted.",
            "Add a concise title describing the page.",
            (title_ref,),
        )
    elif len(title) < conf.title_min_chars or len(title) > conf.title_max_chars:
        _add(
            found,
            url,
            "title.length",
            "info",
            "Review page title length",
            f"Title: {len(title)} chars; advisory: {conf.title_min_chars}–{conf.title_max_chars}.",
            "Prefer a distinctive, descriptive title; do not optimize solely for character count.",
            (title_ref,),
        )

    # Parser retains all captured title elements while preserving the original first-title API.
    titles = html.titles
    if len(titles) > 1:
        _add(
            found,
            url,
            "title.multiple",
            "warning",
            "Multiple title elements",
            "Multiple <title> elements were captured; which one is used may be ambiguous.",
            "Use one well-formed title element in the document head.",
            tuple(FindingEvidence(t.evidence, t.text[:180]) for t in titles),
        )

    descriptions = [meta for meta in html.meta if meta.name.lower() == "description"]
    present = [meta for meta in descriptions if meta.content.strip()]
    if not descriptions:
        _add(
            found,
            url,
            "description.missing",
            "warning",
            "Missing meta description",
            "No description was extracted; search engines may supply a snippet.",
            "Consider a helpful summary when it improves search presentation.",
            (_ev(url, "document", "No meta[name=description] captured"),),
        )
    elif not present:
        _add(
            found,
            url,
            "description.empty",
            "warning",
            "Empty meta description",
            "All extracted meta descriptions have empty content.",
            "Write a useful description or remove unnecessary empty metadata.",
            tuple(_tag_ev(t) for t in descriptions),
        )
    if len(descriptions) > 1:
        distinct = {t.content.strip().casefold() for t in descriptions}
        _add(
            found,
            url,
            "description.conflicting" if len(distinct) > 1 else "description.duplicate",
            "warning",
            "Conflicting meta descriptions"
            if len(distinct) > 1
            else "Repeated meta description tags",
            "Multiple description tags were extracted from the same document.",
            "Keep one unambiguous description tag.",
            tuple(_tag_ev(t) for t in descriptions),
        )
    if len(present) == 1:
        value = present[0].content
        if len(value) < conf.description_min_chars or len(value) > conf.description_max_chars:
            _add(
                found,
                url,
                "description.length",
                "info",
                "Review meta description length",
                f"Length: {len(value)}; advisory: {conf.description_min_chars}–{conf.description_max_chars}.",
                "Prefer a clear summary over a rigid character target.",
                (_tag_ev(present[0]),),
            )

    h1s = [h for h in html.headings if h.level == 1]
    if not h1s:
        _add(
            found,
            url,
            "heading.h1_missing",
            "warning",
            "No H1 heading detected",
            "No H1 was extracted from the supplied HTML.",
            "Consider a descriptive main heading for readability and structure.",
            (_ev(url, "document", "No H1 captured"),),
        )
    elif len(h1s) > 1:
        _add(
            found,
            url,
            "heading.multiple_h1",
            "info",
            "Multiple H1 headings",
            "Multiple H1 headings can be valid in HTML; review whether the page outline is clear.",
            "Make the main subject clear; multiple H1s are not automatically an SEO error.",
            tuple(FindingEvidence(h.evidence, h.text[:180]) for h in h1s),
        )
    previous_level = 0
    for h in html.headings:
        if previous_level and h.level > previous_level + 1:
            _add(
                found,
                url,
                "heading.skipped_level",
                "info",
                "Heading level jump",
                f"Jump from H{previous_level} to H{h.level}; review heading structure.",
                "Review whether the heading structure represents the document sections clearly.",
                (FindingEvidence(h.evidence, h.text[:180]),),
            )
        previous_level = h.level
        if not h.text.strip():
            _add(
                found,
                url,
                "heading.empty",
                "warning",
                "Empty heading",
                f"An H{h.level} was captured with no text content.",
                "Give visible headings meaningful text or remove unnecessary heading markup.",
                (FindingEvidence(h.evidence, "Empty extracted text"),),
            )

    # Use canonical_tags for evidence, including empty declarations.
    canonicals = html.canonical_tags
    if not canonicals:
        _add(
            found,
            url,
            "canonical.missing",
            "info",
            "No canonical declaration",
            "No HTML canonical was found; not every page requires one.",
            "Add one only if it helps express the preferred URL.",
            (_ev(url, "document", "No rel=canonical link captured"),),
        )
    else:
        normalized: set[str] = set()
        for tag in canonicals:
            target = _norm(tag.href, url) if tag.href.strip() else None
            if target is None:
                _add(
                    found,
                    url,
                    "canonical.invalid",
                    "warning",
                    "Invalid canonical URL",
                    "The canonical is empty, malformed or uses an unsupported URL.",
                    "Use one absolute or valid relative HTTP(S) canonical URL.",
                    (FindingEvidence(tag.evidence, tag.href[:180] or "Empty href"),),
                )
            else:
                normalized.add(target)
                if urlsplit(target).hostname != urlsplit(url).hostname:
                    _add(
                        found,
                        url,
                        "canonical.external",
                        "info",
                        "Cross-domain canonical",
                        "The canonical points to another host; syndication may justify this.",
                        "Confirm the external preferred URL is intended.",
                        (FindingEvidence(tag.evidence, target[:180]),),
                    )
        if len(canonicals) > 1:
            _add(
                found,
                url,
                "canonical.conflicting" if len(normalized) > 1 else "canonical.duplicate",
                "warning",
                "Conflicting canonical declarations"
                if len(normalized) > 1
                else "Repeated canonical declarations",
                "Multiple canonical elements were extracted. Contradictory hints can be ignored.",
                "Use a single preferred canonical URL.",
                tuple(FindingEvidence(t.evidence, t.href[:180]) for t in canonicals),
            )

    robots_meta = [m for m in html.meta if m.name.lower() in ("robots", "googlebot", "bingbot")]
    directives: dict[str, set[str]] = defaultdict(set)
    for meta in robots_meta:
        directives[meta.name.lower()].update(
            part.strip().lower() for part in meta.content.split(",") if part.strip()
        )
    for agent, commands in sorted(directives.items()):
        noindex = "noindex" in commands or "none" in commands
        nofollow = "nofollow" in commands or "none" in commands
        if noindex:
            metas = tuple(_tag_ev(t) for t in robots_meta if t.name.lower() == agent)
            _add(
                found,
                url,
                "robots.noindex",
                "info",
                f"Noindex directive for {agent}",
                "Noindex found. HTTP X-Robots-Tag headers were not checked.",
                "Confirm this page is intended to remain out of search results.",
                metas,
            )
        if nofollow:
            metas = tuple(_tag_ev(t) for t in robots_meta if t.name.lower() == agent)
            _add(
                found,
                url,
                "robots.nofollow",
                "info",
                f"Nofollow directive for {agent}",
                "HTML metadata requests that this crawler not follow links on the page.",
                "Confirm the link-following directive is intentional.",
                metas,
            )
        conflict = (noindex and ("index" in commands or "all" in commands)) or (
            nofollow and ("follow" in commands or "all" in commands)
        )
        if conflict:
            _add(
                found,
                url,
                "robots.conflicting",
                "warning",
                f"Contradictory robots directives for {agent}",
                "Conflicting index/follow instructions appear in the same crawler directive group.",
                "Remove conflicting instructions and keep the intended restrictions.",
                tuple(_tag_ev(t) for t in robots_meta if t.name.lower() == agent),
            )
    if directives.get("robots") and directives.get("googlebot"):
        generic, google = directives["robots"], directives["googlebot"]
        if ("noindex" in generic) != ("noindex" in google) and (
            "index" in google or "noindex" in google
        ):
            _add(
                found,
                url,
                "robots.agent_difference",
                "info",
                "Crawler-specific indexing instructions differ",
                "Generic and Googlebot indexing directives differ; this may be intentional.",
                "Confirm the different crawler directives are intended.",
                tuple(_tag_ev(t) for t in robots_meta if t.name.lower() in ("robots", "googlebot")),
            )

    internal_links: list[tuple[str, object]] = []
    src_host = urlsplit(url).hostname
    for link in html.links:
        try:
            target = urlsplit(link.href)
            if target.hostname != src_host:
                continue
            internal_links.append((link.href, link))
        except ValueError:
            continue
    if not internal_links:
        _add(
            found,
            url,
            "links.no_internal",
            "info",
            "No internal links detected",
            "No internal anchor links were found; standalone pages may not need them.",
            "Review navigation and context where internal links would help users.",
            (_ev(url, "document", "No matching-host anchor links captured"),),
        )
    elif urlsplit(url).scheme == "https":
        insecure = [link for href, link in internal_links if urlsplit(href).scheme == "http"]
        if insecure:
            _add(
                found,
                url,
                "links.insecure",
                "warning",
                "Internal HTTP links from HTTPS page",
                "Some same-host links use unencrypted HTTP URLs.",
                "Update these links to the appropriate HTTPS destination.",
                tuple(FindingEvidence(t.evidence, t.href[:180]) for t in insecure[:25]),
            )
    return found


def analyze_page(snapshot: PageSnapshot, config: RuleConfig | None = None) -> AnalysisReport:
    """Inspect a single immutable snapshot, without fetching URLs or calling models."""
    return analyze_pages((snapshot,), config)


def analyze_pages(
    snapshots: Iterable[PageSnapshot],
    config: RuleConfig | None = None,
) -> AnalysisReport:
    """Deduplicate normalized page URLs and detect repeated titles across pages."""
    config = config or RuleConfig()
    grouped: dict[str, list[PageSnapshot]] = defaultdict(list)
    for page in snapshots:
        try:
            url = normalize_url(page.final_url).value
        except UnsafeTarget:
            raise ValueError("Snapshot has an invalid final URL") from None
        grouped[url].append(page)
    pages: list[PageSnapshot] = []
    duplicates = 0
    for url in sorted(grouped):
        matches = grouped[url]
        duplicates += len(matches) - 1
        # Deterministic selection even when incoming snapshots are re-ordered.
        pages.append(min(matches, key=lambda p: (p.captured_at.isoformat(), p.final_url)))
    results: list[SeoFinding] = []
    title_index: dict[str, list[tuple[str, FindingEvidence]]] = defaultdict(list)
    for page in pages:
        results.extend(_html_findings(page, config))
        title = page.html.title
        if title and title.strip():
            reference = page.html.title_evidence or Evidence(page.final_url, "document", 1)
            title_index[" ".join(title.split()).casefold()].append(
                (page.final_url, FindingEvidence(reference, title[:180]))
            )
    for titles in title_index.values():
        if len(titles) > 1:
            evidences = tuple(item[1] for item in sorted(titles))
            for url, _ in titles:
                _add(
                    results,
                    url,
                    "title.duplicate_pages",
                    "warning",
                    "Title reused across pages",
                    "Multiple pages use this title; check whether it should be distinctive.",
                    "Consider distinctive titles for pages with different purposes.",
                    evidences,
                )
    results.sort(
        key=lambda f: (
            f.url,
            f.rule_id,
            tuple(
                (x.reference.source_url, x.reference.element, x.reference.ordinal)
                for x in f.evidence
            ),
        )
    )
    return AnalysisReport(len(pages), duplicates, tuple(results))
