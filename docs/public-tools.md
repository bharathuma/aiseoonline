# Public SEO tools

Nine deterministic SEO tools provide free, anonymous checks. The internal-link tool probes at most three additional same-origin URLs without downloading their bodies. Their code and routes are implemented, but they are not deployed publicly by this repository.

## Run locally

Start the Docker Compose stack using the instructions in [getting started](getting-started.md), then browse:
- `http://127.0.0.1:4321/tools/robots-txt-validator/`
- `http://127.0.0.1:4321/tools/xml-sitemap-validator/`
- `http://127.0.0.1:4321/tools/meta-tag-checker/`
- `http://127.0.0.1:4321/tools/redirect-chain-checker/`
- `http://127.0.0.1:4321/tools/canonical-url-checker/`
- `http://127.0.0.1:4321/tools/structured-data-checker/`
- `http://127.0.0.1:4321/tools/heading-structure-analyzer/`
- `http://127.0.0.1:4321/tools/internal-link-checker/`
- `http://127.0.0.1:4321/tools/social-metadata-checker/`

The web server forwards `/api/` to FastAPI. The same proxy is configured for the Astro development server. Redis must be available: quota enforcement fails closed with HTTP 503 when Redis is down.

## API

All endpoints are `POST`, under `/api/v1/tools/`, with a JSON body containing an absolute public URL:

```json
{"url": "https://example.org/"}
```

| Route | Input | What gets fetched |
| --- | --- | --- |
| `/robots` | Website address | The origin's `/robots.txt` only |
| `/sitemap` | Full XML sitemap URL | Robots.txt and the one requested sitemap |
| `/meta` | One HTML page URL | Robots.txt and the one requested page |
| `/redirects` | Starting URL | Robots.txt and one bounded same-origin chain of HTTP response headers |
| `/canonical` | One HTML page URL | Robots.txt and page HTML; canonical targets are not fetched |
| `/schema` | One HTML page URL | Robots.txt and page HTML; JSON-LD remains inert data |
| `/headings` | One HTML page URL | Robots.txt and page HTML; H1–H6 order and advisory warnings |
| `/links` | One HTML page URL | Page HTML and at most three same-origin header-only link probes, all robots-aware |
| `/social` | One HTML page URL | Page HTML only; Open Graph and X/Twitter metadata; no image fetching |

Results contain the checked URL, timestamp, observed facts, and structured issues with evidence. Responses are JSON and can be downloaded in the browser. Error codes use the project's [API error contract](api-contracts.md).

## Interpretation and limits

- **Robots:** reports syntax and compatibility warnings. It does not verify how Googlebot or other crawlers would interpret the file.
- **Sitemap:** checks one XML document, supporting the standard namespace, urlsets and sitemap indexes. It does not fetch linked sitemaps or verify that listed URLs are reachable or indexed. Document type declarations and XML entities are rejected.
- **Meta tags:** uses real fetched HTML and the deterministic [SEO rule engine](seo-rules.md). Checks are based on extracted HTML, not browser-rendered JavaScript or search-engine snapshots. HTTP headers such as X-Robots-Tag are not yet evaluated.

Public checks reuse the restricted crawler's DNS/IP validation, pinned connections, redirect rules, robots awareness, one-page limits, timeouts, and streamed byte caps. A sitemap is limited to 512 KiB and 1,500 inspected entries; robots.txt is capped at 96 KiB. The page checker uses the crawler's 1 MiB limit.

Redis enforces a shared budget of 12 requests per connecting peer and 120 per destination hostname within rolling 60-minute expiry windows. Rate limits apply across all nine tools. When reverse proxies aggregate clients behind one IP, the peer budget also aggregates them. **Deployment must configure a verified real-client IP trust boundary and edge protections** before public launch. Never trust arbitrary forwarded IP headers directly.

No authentication or verified-site deep scan is enabled. No external targets are contacted during CI.

For details of redirects, canonical URLs and JSON-LD, see [these checkers](advanced-tools.md). For heading outlines, bounded internal-link verification and social metadata, see [final deterministic tools](final-deterministic-tools.md).

## Verification

```sh
uv run --project apps/api --locked pytest apps/api/tests/test_public_tools.py -q
pnpm test:web
pnpm check:web
pnpm build:web
pnpm e2e:web
```

API tests use local fixtures with pinned, simulated public DNS answers; browser tests intercept the API and cover successful and error results. The GitHub Actions workflows run the full checks. No LLM or third-party API keys are required.
