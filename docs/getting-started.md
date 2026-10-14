# Local development

This guide covers the initial web and API foundation. Database, workers, SEO tools, and AI processing are not yet implemented.

## Prerequisites

- Node.js 22.12 or newer and Corepack
- pnpm 10, managed through Corepack
- Python 3.12 or newer
- uv for Python dependencies

## Install

From the repository root:

```bash
corepack enable
pnpm install
uv sync --project apps/api --group dev
```

Neither OpenAI credentials nor a database is needed for the current foundation.

## Run the website

```bash
pnpm dev:web
```

Open http://127.0.0.1:4321. The homepage is a real Astro page with a searchable React directory of **planned** tools. It does not offer live SEO checks yet.

## Run the API

In a separate terminal at the repository root:

```bash
uv run --project apps/api uvicorn aiseoonline_api.main:app --reload --host 127.0.0.1 --port 8000
```

- Health: http://127.0.0.1:8000/api/v1/health
- API docs: http://127.0.0.1:8000/api/docs
- OpenAPI: http://127.0.0.1:8000/api/v1/openapi.json

Configuration uses `AISEO_`-prefixed environment variables. Copy `.env.example` to `.env` only if you need to change defaults. Optional model credentials are not used yet.

## Checks

```bash
uv run --project apps/api pytest apps/api/tests -q
uv run --project apps/api ruff check apps/api
pnpm test:web
pnpm check:web
pnpm build:web
```

A GitHub workflow runs these checks on pull requests. Dependency lockfiles should be committed once a registry-enabled installation resolves them; do not invent lockfiles or checksums. Until then, the web CI install uses `--no-frozen-lockfile`.

## Repository layout

- `apps/api`: installable FastAPI Python package and tests
- `apps/web`: Astro pages, React components, Tailwind styles, and tests
- `apps/worker`: reserved asynchronous worker
- `packages`: reserved shared modules, described in their READMEs
- `infra`: reserved deployment configurations

See [development.md](development.md) and [SECURITY.md](../SECURITY.md).
