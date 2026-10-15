# SEO rules

The rule engine consumes existing `PageSnapshot` objects and produces immutable, ordered findings with a rule identifier, severity, affected URL, human explanation, suggested correction, and concrete source evidence. It never fetches URLs, runs JavaScript, or calls a language model.

## Usage

```python
from aiseoonline_api.crawler import CrawlSession
from aiseoonline_api.seo_core import RuleConfig, analyze_page

# Only crawl sites you own or are authorized to check.
snapshot = CrawlSession("https://your-authorized-domain.org/").fetch_page()
report = analyze_page(snapshot, RuleConfig())
for finding in report.findings:
    print(finding.rule_id, finding.url, finding.severity)
    print(finding.to_storage())  # values for the existing SeoFinding ORM columns
```

`analyze_pages(...)` deduplicates pages by normalized final URL and can identify repeated HTML title text across an input collection. No multi-page crawler endpoint or verified-site scan is enabled by this module. Rule IDs remain stable for downstream API, audit, and reporting consumers.

## Checks

- Missing, unusually short/long, or repeated titles, and repeated titles across input pages.
- Missing, empty, repeated, or contradictory meta descriptions; advisory length review.
- Missing/empty H1 headings, multiple H1 elements, heading-level jumps.
- Missing, empty, malformed, duplicate, conflicting, or cross-domain canonical declarations.
- HTML meta robots noindex/nofollow signals and conflicting directives; differences among crawler-specific instructions.
- Internal-link absence and same-host HTTP links found on HTTPS pages.

Warnings describe conditions worth reviewing, **not guaranteed ranking problems**. Informational notices should not be turned into an SEO score without additional context. Length ranges are configurable editorial suggestions, not standards enforced by search engines.

## Evidence and limitations

Evidence references preserve the source URL, element identifier and ordinal from the parser. For missing elements, the document reference explains which field was absent from the **bounded HTML extraction**, rather than claiming something about all rendered HTML. Parsing does not execute scripts; dynamically injected content, HTTP `X-Robots-Tag`, header-level canonicals, CSS-hidden text, JavaScript-generated links, and external destinations are not evaluated. Links are not visited by these rules, so they are never labeled "broken" here. The HTML parser has explicit extraction caps, which can undercount very large documents. Canonicals are hints, and more than one H1 is not automatically a search-engine error.

The initial database model's `SeoFinding.evidence` JSON column can store the `to_storage()` evidence object. Caller-provided tenant and audit identifiers must be supplied through authorized application logic; this module performs no persistence.

## Tests

```sh
uv run --project apps/api --locked pytest apps/api/tests/test_seo_rules.py -q
```

Tests use synthetic local HTML fixtures and do not request external websites. The engine must return the same ordered results for equivalent inputs without model calls.