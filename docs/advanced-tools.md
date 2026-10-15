# Redirect, canonical and structured data tools

These three tools use the existing bounded, robots-aware crawler and the Redis-backed anonymous quota. They are implemented for local development; no production deployment is included in this change.

## Redirect chain checker

Enter the **starting URL**, such as `https://example.org/old-path`.

The report contains the observed HTTP status, source URL and safe Location header for each fetched hop, plus the termination reason and final known status when the chain completes. A maximum of three same-origin redirects may be followed. The tool checks robots.txt first and applies the same DNS vetting, pinned-IP connections, deadlines, politeness and concurrency limits as the standard crawler. It fetches **headers only** for the target chain, not bodies.

The result explicitly marks a loop, exceeded budget or blocked destination. External-origin, local/private-address and HTTPS-to-HTTP downgrade destinations are **not contacted**. The tool cannot verify final HTTP status after a blocked or exceeded redirect; it reports only observed hops. A 302 or 307 is a real HTTP status, not inherently an SEO failure.

## Canonical URL checker

Enter one publicly reachable **HTML page URL**, such as `https://example.org/page/`.

The page is fetched once. We parse its HTML `<link rel="canonical">` declarations and preserve tag ordinals and original `href` values. Each declaration is classified as:

- **Self-referencing:** it resolves to the fetched page URL.
- **Relative:** it resolves to another path, starting from the fetched page URL.
- **Absolute:** it uses an absolute HTTP(S) URL on the same hostname.
- **External:** it uses an absolute HTTP(S) URL on another hostname.
- **Invalid:** the declaration is empty, malformed or not a permitted HTTP(S) URL.

Absent and conflicting declarations are identified through the existing deterministic [SEO rule engine](seo-rules.md). Relative, missing, and external canonicals are **not automatically errors**. The checker does not crawl a canonical target, read HTTP Link canonical headers, inspect rendered JavaScript, or know which canonical Google ultimately selects.

## JSON-LD checker

Enter one public HTML URL, such as `https://example.org/article/`.

Only `<script type="application/ld+json">` blocks captured by the existing HTML parser are inspected. We parse bounded JSON without running scripts or fetching referenced URLs. The report lists extracted JSON-LD blocks, structurally recognizable nodes, declared types and common schema.org types.

Detected problems include invalid JSON, malformed `@graph`, absent `@context`, missing `@type` and invalid top-level shapes. Unknown extension types are not assumed invalid. There is a cap of 20 captured scripts, 8 KiB of extracted text per script, and 50 inspected graph nodes per block.

**This is not Google Rich Results Test.** It does not prove schema.org conformance, validate all type-specific required/recommended properties, guarantee rich-result eligibility, or predict search rankings. For those purposes, consult current search-engine documentation and official validators.

## API and security

The three JSON endpoints are `POST /api/v1/tools/redirects`, `/canonical`, and `/schema` with `{"url":"https://example.org/"}`. Results use the same typed report, issue and evidence contract as the first three tools. Unauthorized deep scans remain disabled. Redis limits apply across all six tools.

No external host is requested during CI. Redirect tests use a controlled local HTTP fixture and the existing simulated public-DNS-to-loopback socket pinning. The browser tests intercept API responses to check UI states.

```sh
uv run --project apps/api --locked pytest apps/api/tests/test_crawler.py apps/api/tests/test_advanced_tools.py -q
pnpm test:web
pnpm check:web
pnpm build:web
pnpm e2e:web
```

Before production, the existing project still needs trusted client-IP propagation through proxies, edge abuse controls and outbound network restrictions. Do not use this PR as deployment approval.
