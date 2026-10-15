# Application quality and performance review

## Scope and execution boundaries

The browser suite uses local Astro preview and explicitly scripted API responses for
public SEO result rendering, networking failures and downloads. It does **not**
represent third-party crawl correctness or a hosted-production browser session.
Backend test suites separately cover deterministic SEO extraction, URL and DNS
restrictions, Redis admission control, PostgreSQL persistence, audited Celery
recovery and development-only private LangGraph/RAG features.

Account APIs are exercised through a real PostgreSQL/Redis integration test and
a controlled hosted-verification-file substitute. Production self-registration,
private RAG chat and multi-page auditing remain disabled by design; no end-to-end
production paid-AI user journey has been certified.

### Verified coverage inventory

| Area | Automated checks | Boundaries |
| --- | --- | --- |
| All nine free SEO checkers | Playwright each route: validated request, successful evidence, issue rendering, JSON download | Explicitly mocked API fixture responses |
| AI metadata tool | Existing browser success, model-unavailable error, editable suggestions | Fixture LLM responses |
| Mobile | Tool page at 320, 375, 390, 768, 1024px; existing homepage at 375, 768, 1440px | Chromium viewport emulation, not physical devices |
| Accessibility | WCAG A/AA axe checks on public tool forms; keyboard navigation and focus; existing homepage audit | Automated scans do not replace human screen-reader/contrast review |
| Network and retries | Quota/server error, transport abort, invalid input, follow-up success, no stale result | Scripted network and app state |
| Accounts | Real PostgreSQL and Redis registration/login, challenge, CSRF, ownership, export, deletion; existing cross-user negative tests | Test account, synthetic domain, controlled verification response |
| Agents and private reports | Existing PostgreSQL/Celery audit lifecycle, idempotency, cancellation, failure/recovery and private UI tests | Developer-only endpoints; no production deep scan |
| Private RAG | Existing isolated retrieval, project scoping, citation and development-chat tests | No live private production chat |
| Quotas | Twenty-request in-process burst; real concurrent Redis tests for per-visitor and per-site admission | No Internet load, cloud autoscaling or distributed worker benchmark |
| Databases | Confirm key ownership, leasing, full-text, session indexes; explain/analyze bounded project query | Small CI data only; no production cardinality or slow-query history |
| Dependencies | Existing locked Python and frontend audits in GitHub Actions | Does not establish absence of all vulnerabilities |

## Defects corrected

1. Anonymous visitor requests denied by their personal hourly limit previously
   **still incremented the site's shared allowance**. The Redis Lua operation now
   checks *both* limits before either counter increments, with concurrent real Redis
   regression tests preventing site-quota depletion or over-admission.
2. The social preview component could throw when an unexpected partial server
   result omitted the preview object. It now renders bounded fallback text without
   executing or trusting remotely supplied HTML.
3. Account project creation counted loaded rows and could race under simultaneous
   owners' requests. The PostgreSQL creation transaction now locks the owning user
   row and performs an indexed SQL count before admitting the project; list/export
   queries have stable ordering and a ten-record limit. PostgreSQL integration tests
   cover the account workflow; full multi-process race/load qualification remains
   a separate requirement.

## Actual measurements

Measurements are emitted by the checked-in scripts/tests:

- `QA_API_LOAD|` — twenty concurrent mocked API calls; timings include a
  **synthetic 25ms fetch delay** and in-process framework costs.
- `QA_WEB_BUILD|` — Astro static output counts and **uncompressed disk sizes**,
  not transfer sizes or Core Web Vitals.
- `QA_WEB_NAVIGATION|` — local headless Chromium preview navigation durations,
  not real-user field performance or a CDN benchmark.
- `QA_DB_PLAN|` — `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for a bounded indexed
  owner-project query on a **small test database**, not representative production load.

### Recorded CI samples — October 15, 2026 (UTC)

The following are measurements from [Foundation checks run
38739659158](https://github.com/bharathumashankar/aiseoonline/actions/runs/38739659158)
and [PostgreSQL infrastructure run
38739659098](https://github.com/bharathumashankar/aiseoonline/actions/runs/38739659098).
Measurements are *observed results*, not targets or guaranteed throughput.

| Measurement | Observed | Environment / qualification |
| --- | ---: | --- |
| Controlled API burst | 20/20 HTTP 200 | In-process, stubbed 25ms crawl |
| Peak concurrent crawls | 4 | Four application-local semaphore slots |
| API latency p50 / p95 | 74.18 / 123.27 ms | Includes artificial crawler delay |
| Static HTML pages | 22 | Local Astro production build |
| Total JavaScript / CSS | 258,571 / 29,218 bytes | **Uncompressed disk** sizes, all generated bundles |
| Largest single JS bundle | 212,848 bytes | Uncompressed disk size |
| Meta tool HTML | 12,229 bytes | Uncompressed disk size |
| Preview navigation: meta / sitemap / AI meta | 28 / 12 / 11 ms | Headless Chromium, localhost preview |
| Owned-project SQL execution | 0.026 ms | PostgreSQL EXPLAIN ANALYZE, **0 returned rows**, CI fixture |
| Automated API tests | 322 passed, 18 skipped | Foundation run; aggregate Python coverage 78% |
| PostgreSQL/Redis/worker suite | 340 passed | Infrastructure run |
| Playwright browser checks | 50 passed (+2 development-only) | Chromium CI browser |

The SQL timing is for an almost empty **test** table and must not be used to
forecast production latency. Browser navigation is local to the CI runner and
is not a real-user Core Web Vitals sample. The 258 KB aggregate JavaScript
does not represent what any one user necessarily downloads.

Numbers from different machines or deployment modes are **not** suitable for
direct performance comparisons. Re-run commands:

```sh
uv run --project apps/api --locked pytest apps/api/tests/test_public_load.py -q -s
uv run --project apps/api --locked pytest apps/api/tests/test_quality_integration.py -q -s
pnpm build:web
node apps/web/scripts/report-build-size.mjs
pnpm e2e:web
```

The PostgreSQL/Redis tests skip locally without the explicitly configured test
services. Their real execution is required in the infrastructure workflow.

## Browser caching and deployment

`apps/web/public/_headers` is a **Cloudflare Pages static-host configuration**
and is not a universal setting for VPS Nginx, Astro preview, or all Cloudflare
Worker deployment modes. Where supported, normal static HTML is revalidated and
fingerprinted `/_astro/*` assets get year-long immutable caching. All HTTP
responses from private API routes must continue to use `no-store`; do **not**
cache authentication cookies, paid model results, audit reports or private RAG
text at the edge. The reverse proxy/CDN administrator must test actual HTTP
headers after deployment. No CDN or public production setting is changed here.

## Remaining release gates

- **Production paid/private operations:** verified account access must be wired
  into all private audit/RAG routes and background recovery; multi-page crawler
  authorization and budgets must be implemented and verified before enabling.
- **Human accessibility and device testing:** manual screen-reader evaluation,
  visual focus/contrast, touch ergonomics and physical low-end phone testing are
  still needed. Automated axe and viewport tests are not WCAG certification.
- **Real-user performance:** collect production RUM Core Web Vitals,
  network-specific p75 LCP/INP/CLS, slow database logs and index statistics,
  worker saturation and actual CDN cache headers before asserting production
  throughput or performance. Headless local timing is not field evidence.
- **Infrastructure security:** inspect actual egress rules, cloud-metadata denial,
  ingress/proxy identity and bot/WAF challenges independently.
- **Private-content retention:** audit checkpoint/backup deletion and complete
  private-data portability remain incomplete and were not silently added here.
- **External service behavior:** no live paid LLM quality/cost test, production
  website owner proof, or third-party robots/crawl load test was executed.

## Quality decision

The public deterministic tool *fixture journeys* are suitable for automated
regression gating once the recorded CI is green. There is no assertion that every
critical journey is ready for production or that no unknown bug remains.
In particular, private/paid/deep-audit release readiness is **not established**.
