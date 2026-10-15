# Secure website crawler

The crawler is reusable Python code, **not** a public website endpoint. It does not automatically request or index any third-party site.

## Network safety

- Accept absolute HTTP or HTTPS URLs on default ports only; reject userinfo, reserved hostnames, and non-public IPs.
- Validate *every* DNS response address, including mixed public/private answers. Dial the vetted numeric IP directly, avoiding a second DNS lookup. HTTPS verifies the original hostname using system CA roots and SNI.
- Revalidate every redirect; keep requests within the original scheme/host/port origin and reject HTTPS downgrades and loops.
- Enforce a 1 MiB public HTML budget, 96 KiB robots budget, three redirects, connect/DNS/total deadlines, bounded headers and two concurrent HTTP requests across the process. Identity-only encoding prevents compressed-body expansion.
- Read robots.txt before a page. Follow compatible rules and applicable crawl-delay. A robots error other than 404/410 denies the crawl.

## Extracted evidence

Each immutable page snapshot records the requested/final URL, UTC capture timestamp, HTTP status, redirects and byte count. Parsing extracts titles, meta tags, H1–H6 headings, canonical declarations, links, robots directives and raw JSON-LD text with source and ordinal evidence.

HTML is treated solely as untrusted **data**. No scripts execute and no page content is used as application instructions. Invalid encodings are flagged.

## Scope and operation

A public session allows **one attempted page**. Multi-page limits cannot be enabled by a user-provided flag. There is no public route yet; authentication, proof of website ownership, per-account budgets and rate limiting must be built before exposing site crawling.

Example for authorized website owners:

```python
from aiseoonline_api.crawler import CrawlSession

snapshot = CrawlSession("https://your-authorized-domain.org/").fetch_page()
print(snapshot.html.title, snapshot.final_url)
```

Run the controlled tests with:

```sh
uv run --project apps/api --locked pytest apps/api/tests/test_crawler.py -q
```

CI makes **no external website requests**. Tests run against a local in-process HTTP fixture; the test substitutes public DNS answers while asserting that the HTTP transport dials only the validated address. Test bypasses are not exposed in production configuration.

## Deployment prerequisites

Even after application security tests pass, apply independent network egress ACLs, ensure minimum data retention, support project ownership and authorization, add global quotas and abuse protection, and review crawler policies before accepting visitor URLs. Slow DNS lookups are bounded by a four-thread ceiling; use network isolation as a second layer, not as a replacement for code checks.
