# Public SEO publishing, measurement and ad-readiness checklist

## Current scope

The public site has ten implemented tool pages: nine deterministic single-resource
checks and an optional model-assisted metadata generator. All ten have individually
written explanatory content, source-scoped examples, troubleshooting advice and
visible FAQs. Tool page structured data includes visible FAQ questions and
breadcrumb links. The nine deterministic checkers use free web application
markup; the optional paid-provider-dependent tool does **not** claim to be
universally free. An illustrative example is never a live test or promise of
a ranking outcome.

The static `/sitemap.xml` uses an allowlist of known public routes, including
ten tool pages and four operator-review information pages. The `/robots.txt`
points to it and disallows `/internal/` and `/api/` as crawler guidance.
Private development pages also have a `noindex` meta directive and the
Docker/Nginx origin sends `X-Robots-Tag: noindex, nofollow, noarchive` for
`/internal/`. **Robots directives are not security boundaries**: access to
private user data must require authentication, and production development
APIs remain disabled.

## Publishing review before going live

- Verify each tool's real API contract in the deployed environment. A visible
  form is not evidence that the backend is configured or publicly reachable.
  Confirm quotas, response times, intended limitations and AI error states.
- Review page titles, descriptions, canonical URLs and the XML sitemap for
  duplicates, incorrect redirects, removed routes or misleading claims.
  Sitemap inclusion is not a guarantee of discovery or indexing.
- Check server responses: 200 for real tools, 404 for missing content, and
  `noindex` headers for internal/development pages. Do not include private
  dashboards, query-driven searches or user-specific reports in a sitemap.
- Check page HTML and JSON-LD with a parser and a search-engine rich-result
  test where applicable. The FAQPage objects match visible text and are not
  promised to generate FAQ enhancements in search. Keep software offer
  assertions consistent with actual public availability.
- Edit the four operator-review pages with a real, verified legal/service
  operator identity, jurisdiction, contact channel and privacy/retention
  policy. **Do not publish them as final legal documents without review.**
- Maintain useful links from the home directory, tools, related guides and
  relevant policy pages. Avoid adding near-identical keyword-variant URLs,
  invented testimonials, fake visitor figures or search-engine guarantees.
- Run automated accessibility checks plus a manual keyboard, screen-reader,
  contrast and mobile touch review for new or modified content.
- Verify the actual origin/CDN cache policy: HTML can be revalidated;
  hashed assets may cache immutably; private API content and sessions must
  never be cached at the edge.
- After an approved deployment, submit the sitemap URL in the relevant
  webmaster tools, monitor crawl access/indexing, investigate canonicalization
  and review real search queries before proposing new content. Do not
  repeatedly request indexing as a substitute for content improvements.

## Consent-ready, disabled-by-default analytics

Both flags below default to false and **remain false in the current build**:

```text
PUBLIC_AISEO_ANALYTICS_ENABLED=false
AISEO_ANALYTICS_ENABLED=false
```

No third-party analytics script, cookie, network beacon or API usage credential
is present in the default frontend. The first-party endpoint
`POST /api/v1/analytics/pageview` returns 404 by default. If a future
operator explicitly approves the feature, **both** server and frontend
flags must be set, the production privacy policy reviewed, and the real
ingress logs and Redis behavior tested. The frontend asks for a deliberate
opt-in on the Privacy page; the preference is stored in browser localStorage,
not an analytics cookie. It sends only one allowlisted pathname on each
navigation, without URL queries, referral strings, identity or page text,
and respects Do Not Track. A withdrawn preference stops later collection
but does not automatically erase past aggregated counts.

The server accepts only approved public paths, counts by UTC day and path
under Redis keys with a 30-day expiry, and caps each day's stored count at
10,000 per path. There is no session/user ID or page content in those keys.
Counts represent events, **not unique people or verified human visitors**.
Redis and host/Cloudflare access logs may independently capture request
metadata; actual privacy compliance requires operator review, edge bot
controls, retention policy and secured service configuration. No dashboard,
accuracy claim or public visitor statistic is enabled.

## Future ad layouts

`PUBLIC_AISEO_AD_SLOTS_ENABLED=false` by default. When a site operator
chooses to preview placements, a clearly labeled, noninteractive reserved
slot uses a minimum 280px height to prevent sudden layout shifts.
No ad script, iframe, monetization SDK, click handler, tracking URL or
network is installed. An ad vendor must not be introduced without separate
authorization, consent/legal review, CSP approval, responsive manual
testing and independent Core Web Vitals measurements. Never make ads
look like SEO results or navigation controls; reserve stable placement
before fetching any future creative.

## Repeatable checks

```sh
pnpm check:web
pnpm lint:web
pnpm build:web
pnpm e2e:web
uv run --project apps/api --locked pytest apps/api/tests/test_analytics.py -q
```

The browser tests enumerate all ten landing pages, require distinct
metadata, visible instructional sections, matching structured data,
indexable canonicals, no private sitemap URLs and no tracking or ad
network calls by default. CI measurements apply to a local/isolated
preview, not a real indexed or revenue-generating production site.
