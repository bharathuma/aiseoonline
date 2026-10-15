# AI title and meta description generator

The tenth SEO tool drafts **three editable title/description pairs** from either visitor-pasted text (100–3,000 characters) or one public URL. AI responses are **suggestions**, not deterministic audit findings. The nine existing tools remain free of model calls and separate from this tool.

## How it works

1. The user supplies **either** pasted content or a public HTTP(S) page URL, not both. Pasted text is used only for generation; it is never cached.
2. URL mode uses the existing secured, robots-aware, single-page crawler with restricted DNS/IP resolution, same-origin redirect checks, timeouts and response-size limits. Only the fetched HTML's **title, meta descriptions and up to twelve headings** are used as evidence; body paragraphs, private pages and JavaScript-rendered content are not captured.
3. A versioned trusted `meta_draft/v1` prompt (from the existing provider layer) requests exactly three distinct suggestions, each with a contiguous quote copied from source text and a rationale. Page content always stays in the **untrusted user-data field**, never the trusted system role.
4. The provider requests JSON schema guidance. Pydantic validates all fields, lengths, exact suggestion count and distinct titles/descriptions. An evidence quote that does not occur in the real source **rejects the response**, rather than pretending it is verified.
5. Deterministic post-review flags numbers not found in the source, selected unverified promotional phrases, weak literal topic overlap and advisory character ranges. These checks **cannot prove every AI claim**; the UI explicitly asks the user to verify all statements before publishing.
6. The user can edit and copy every title or description. Live character counts update after editing; server warnings are labeled as referring to the original generated draft.

The suggested title range (30–60 characters) and meta description range (70–160 characters) are **editorial guidelines**, not search engine snippet display guarantees. Search engines use rendered pixel width, query context, and may replace snippets. No keyword volume, traffic, cost or ranking statistics are invented.

## Paid-call controls

The backend requires all of the following for the public AI route to operate:
- `AISEO_OPENAI_API_KEY` (backend only)
- `AISEO_REDIS_URL` with a working Redis instance
- The **actual configured model's rates**: `AISEO_LLM_INPUT_USD_PER_MILLION` and `AISEO_LLM_OUTPUT_USD_PER_MILLION` (both required; no built-in guessed rates)
- Budget controls: `AISEO_AI_META_REQUEST_USD_CAP` (default $0.05) and `AISEO_AI_META_DAILY_USD_CAP` (default $2)

The route fails closed with an informative 503 when credentials, pricing or budget infrastructure are unavailable. A Redis Lua script limits each connecting peer to **three requests per hour**, checked *before* URL fetching. A separate Redis Lua script atomically reserves a conservative worst-case allowance for one generation across **all retry attempts** against a UTC-day global micro-USD budget. Cached URL results use no new model allocation but still count against the visitor's hourly request limit. Without valid configuration no paid request is made.

**Important budget semantics:** The spending counter records **pre-allocated upper bounds**, not an actual OpenAI invoice. Failed generation attempts may consume allocation. Provider-measured token usage and an estimate using configured rates are returned only after success. The cap does not cover any external calls made outside this feature; the OpenAI account's own limits are also recommended. Redis enforces limits across API replicas.

A shared two-slot application semaphore and a provider timeout bound concurrent and long-running generation. Backend logs never contain the supplied text, raw model response or API key. No frontend API credentials are exposed. Requests for pasted text are not cached; URL-based results can be cached by a SHA-256 key of model, prompt version, normalized URL, and extracted source for 15 minutes. The cached response is derived from a **public URL** and stored temporarily in Redis.

### Local configuration

Copy `.env.example`, set the Redis connection, API key, model rates, and optionally adjust caps. Start API and web as documented in [getting started](getting-started.md). Open `/tools/ai-meta-suggestions/` and submit text or a public URL. The route is `POST /api/v1/tools/ai-meta` and accepts either:

```json
{"content": "At least 100 characters describing the actual webpage content, products, services, and relevant facts..."}
```

or `{"url":"https://example.org/article/"}`.

Responses include three suggestions, evidence quotes, rationales, warnings, measured token usage when newly generated, and an optional estimated USD cost. Errors use the existing structured API error contract.

## Tests and limitations

```sh
uv run --project apps/api --locked pytest apps/api/tests/test_ai_meta.py -q
uv run --project apps/api --locked ruff check apps/api
uv run --project apps/api --locked mypy --config-file apps/api/pyproject.toml apps/api/src
pnpm test:web
pnpm check:web
pnpm build:web
pnpm e2e:web
```

All CI model responses are mocked; no live OpenAI API calls or external crawl targets are used. Real API account/billing behavior is **not yet validated** by this PR.

Before live traffic, production operations must explicitly approve deployment, ensure trusted client IP propagation (reverse proxies must not make all visitors share one peer key), outbound egress restrictions, Redis reliability, and provider-side financial alerting. Rate limits alone are not a substitute for provider/account spending controls. This PR does not deploy, merge or change billing settings.
