# AISEOOnline

Open-source SEO tools for checking, understanding, and improving websites.

**Status: Development foundation available; SEO tools and AI features are still planned.** This repository has not been deployed to the public website.

AISEOOnline is being built for site owners, developers, and teams who need practical SEO checks. The initial code contains an Astro/React website and a FastAPI backend with a health endpoint and OpenAPI documentation.

## Planned features

- **SEO tools:** robots.txt, sitemaps, metadata, redirects, canonical URLs, structured data, headings, internal links, and social tags.
- **Site auditing:** bounded crawling with source-linked findings and reports.
- **AI analysis:** evidence-backed explanations, retrieval over permitted content, and bounded audit workflows.

Technical findings will come from deterministic checks. Model-generated suggestions will not replace site evidence.

## Technology

- Web: Astro, React, TypeScript, Tailwind CSS, pnpm
- API: Python, FastAPI, Pydantic, uv
- Planned: PostgreSQL/pgvector, Redis/Celery, LangChain/LangGraph, model APIs, and observability

See [architecture](docs/architecture.md) and [design decisions](docs/adr/README.md).

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

Optional AI credentials are not needed to start the API. See [local development](docs/getting-started.md) for tests and environment configuration.

## Roadmap

The [roadmap](docs/roadmap.md) covers free SEO tools, site audits, AI-assisted analysis, and deployment. Planned tools are not yet available.

## Contributing

Bug reports, documentation improvements, tests, and tool ideas are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

[Apache License 2.0](LICENSE)

Website: [aiseoonline.com](https://aiseoonline.com)
