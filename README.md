# AISEOOnline

Open-source SEO tools for checking, understanding, and improving websites.

**Status: Website and API foundation, internal secure crawler, and deterministic SEO rules implemented. Nine deterministic SEO tools and an optional, quota-controlled AI meta generator are implemented. Further AI audit features remain planned.** The code has not been deployed to the public website.

AISEOOnline is being built for site owners, developers, and teams who need practical SEO checks. The repository contains an Astro/React website, nine deterministic checkers and one AI meta generator, a FastAPI backend, database migrations, and a background worker. The public interface includes robots.txt, XML sitemap, metadata, redirects, canonical URLs, JSON-LD, headings, internal links and social metadata checkers alongside planned tools and introductory guides. No multi-page or full AI audit is publicly available. The internal [SEO rule engine](docs/seo-rules.md) produces source-backed findings from parsed page snapshots.

## Planned features

- **SEO tools:** nine deterministic checkers and one grounded AI meta generator are implemented; larger AI audits remain planned.
- **Site auditing:** bounded crawling with source-linked findings and reports.
- **AI analysis:** evidence-backed explanations, retrieval over permitted content, and bounded audit workflows.

Technical findings will come from deterministic checks. Model-generated suggestions will not replace site evidence.

## Technology

- Web: Astro, React, TypeScript, Tailwind CSS, pnpm
- API: Python, FastAPI, Pydantic, uv
- Infrastructure: PostgreSQL/pgvector, Alembic, Redis/Celery, Docker Compose
- AI infrastructure: optional OpenAI provider adapter, typed responses, budgets and versioned prompts
- Private RAG foundation: permitted page-section extraction, section-aware chunks, embedding providers, verified-project pgvector search
- Planned AI integrations: LangChain/LangGraph agents, evidence-grounded orchestration, and observability

See [private RAG ingestion](docs/rag-ingestion.md), [AI meta generator requirements](docs/ai-meta-generator.md), [architecture](docs/architecture.md), [LLM provider configuration](docs/llm-provider.md), and [design decisions](docs/adr/README.md).

## Local development

Prerequisites: Node.js 22.12+, Corepack, Python 3.12+, and uv.

```bash
corepack enable
pnpm install
uv sync --project apps/api --group dev

# Website: http://127.0.0.1:4321
pnpm dev:web

# API: http://127.0.0.1:8000 (in another terminal)
uv run --project apps/api uvicorn aiseoonline_api.main:app --reload --host 127.0.0.1 --port 8000
```

Health: `GET /api/v1/health` · API docs: `/api/docs` · OpenAPI: `/api/v1/openapi.json`.

Public tool requests require Redis for shared rate limits. Use Docker Compose or configure AISEO_REDIS_URL; if Redis is unavailable, the check endpoints return 503. Optional AI credentials are not needed to start the API. See [local development](docs/getting-started.md) for tests and environment configuration.

## Roadmap

The [roadmap](docs/roadmap.md) covers free SEO tools, site audits, AI-assisted analysis, and deployment. The nine implemented checkers are ready for local use; other tools remain planned.

## Contributing

Bug reports, documentation improvements, tests, and tool ideas are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE)

Website: [aiseoonline.com](https://aiseoonline.com)
