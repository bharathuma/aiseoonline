# Final deterministic SEO tools

The Heading Structure Analyzer, Internal Link Health Checker, and Open Graph / Social Metadata Checker complete nine free, no-signup, deterministic tools in the source repository. No deployment is implied.

## Heading structure analyzer

Example: `https://example.org/article/`

Returns the actual H1–H6 elements extracted from the **fetched HTML**, in document order, with their text and element ordinals. The visual outline indents by heading level. It reuses existing deterministic rules for missing H1s, heading jumps and empty headings.

**Important:** multiple H1 elements can be legitimate, and there is no universal required number of headings or ranking guarantee. JavaScript-generated headings are not in scope.

## Internal link health checker

Example: `https://example.org/`

The checker classifies anchor links in one fetched HTML page as same-origin (internal) or external. It reports a bounded list of distinct links and checks at most **three internal destinations**, through one shared **five-second** probe budget (following a separately bounded six-second page fetch). Each probe revalidates the destination and redirects using pinned public DNS IPs, the same-origin restriction and robots.txt. The checker requests only response **headers**, not document bodies.

A verified **404/410** response is reported as broken. A verified **5xx** response is reported separately as a server problem, because temporary failure does not prove a permanently broken link. **Not checked**, **unverified** and **robots blocked** statuses must never be interpreted as working or broken. External URLs are never requested. Only the first three eligible, distinct internal destinations in the visible sample are probed; remaining links are explicitly unverified. This is not a website-wide crawl, nor link graph or backlink analysis. Requests are bounded in code, and unverified deep scanning remains disabled.

## Social metadata checker

Example: `https://example.org/article/`

Extracts the original HTML `og:*` and `twitter:*` meta fields without fetching referenced assets. Reports missing common Open Graph fields, conflicting values, and the actual metadata values. A **clearly labeled approximation** presents a candidate title, description, image **reference** and site name. No image is fetched or displayed, and no page content is run as executable code.

The approximate preview is not a pixel-faithful Facebook/X/LinkedIn rendering. Platforms may choose their own formatting, override metadata, crop images, or display cached content. It is not a ranking or sharing guarantee.

## Consistency and testing

All nine tools use the same URL input contract, structured result and evidence issue model, request-ID and error middleware, Redis-backed rate limits, responsive form and copy/download functionality. Their tool catalog pages distinguish implemented tools from planned AI capabilities. The full suite runs under the existing CI.

Focused commands:

```sh
uv run --project apps/api --locked pytest apps/api/tests/test_public_tools.py apps/api/tests/test_crawler.py -q
pnpm test:web
pnpm check:web
pnpm build:web
pnpm e2e:web
```

No third-party websites are contacted during CI. Docker integration tests exercise the site through controlled local fixtures. The existing production considerations—Cloudflare trusted client IP handling, outbound ACLs, abuse monitoring, and explicit deployment approval—remain open.
