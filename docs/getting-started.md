# Local development

## Prerequisites

- Docker with Docker Compose v2 (recommended for the complete stack)
- Node.js 22.12+ and pnpm 10 if running the frontend outside Docker
- Python 3.12+ and uv if running the API outside Docker

## Start the complete stack

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(24))"
# Set AISEO_DB_PASSWORD in .env to that output.
python -c "import secrets; print(secrets.token_hex(24))"
# Set AISEO_REDIS_PASSWORD in .env to the second output.
docker compose up --build -d
docker compose ps
```

Services start in dependency order: PostgreSQL health → migrations → API/worker; Redis health is also required. The web container waits for API readiness. The default endpoints are:

- Web: http://127.0.0.1:4321/
- API liveness: http://127.0.0.1:8000/api/v1/health
- API readiness (PostgreSQL + Redis): http://127.0.0.1:8000/api/v1/ready
- API docs: http://127.0.0.1:8000/api/docs

`/health` is process liveness and remains available if services are down. `/ready` returns HTTP 503 when storage is unconfigured or unreachable. **Migrations are not run automatically by the API.** The one-shot `migrate` service runs `alembic upgrade head` before the API starts.

## Check migrations, Redis and the example worker job

```bash
docker compose exec api alembic -c alembic.ini current
docker compose exec redis sh -c 'REDISCLI_AUTH="$AISEO_REDIS_PASSWORD" redis-cli ping'
docker compose exec api python -c 'from aiseoonline_api.jobs import create_celery_app; from aiseoonline_api.config import get_settings; app=create_celery_app(get_settings()); print(app.send_task("aiseoonline.ping", args=["demo"]).get(timeout=20))'
```

The API, worker and migration service share Python dependencies. Nine anonymous deterministic checkers are implemented. Operator-provisioned account APIs and domain verification exist, while private LangGraph/RAG jobs are available only in restricted development/test configurations. Production self-registration and private audit/chat routes are intentionally disabled. No paid model credential is required for local startup; AI metadata generation fails clearly when not configured.

## Run individual apps without Docker

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm dev:web
uv sync --project apps/api --locked --group dev
uv run --project apps/api uvicorn aiseoonline_api.main:app --reload --host 127.0.0.1 --port 8000
```

Without configured storage, API liveness and docs work, but `/ready` correctly responds with HTTP 503. To use migrations and jobs from the host, set `AISEO_DATABASE_URL` and `AISEO_REDIS_URL` to accessible local services. For Alembic:

```bash
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
uv run --project apps/api alembic -c apps/api/alembic.ini current
```

## Quality and API contracts

See [quality checks](quality.md) for locked installs, linting, type checking, test coverage, vulnerability audits and branch-protection settings. See [API contracts](api-contracts.md) for the error envelope, request identifiers and response schemas.

## Tests and checks

```bash
uv run --project apps/api pytest apps/api/tests -q
uv run --project apps/api ruff check apps/api
pnpm test:web
pnpm check:web
pnpm build:web
# Browser tests (after installing Playwright Chromium)
pnpm --filter @aiseoonline/web exec playwright install chromium
pnpm e2e:web
```

The infrastructure CI job provisions temporary PostgreSQL + pgvector and Redis services to exercise migrations, DB operations and the sample Celery worker. The existing frontend workflow builds the Astro site and runs Chromium browser tests with responsive screenshots attached as CI artifacts. Tests involving a live model provider are not needed.

## Notes

The pgvector extension is required, though the initial schema has no embedding columns. Store password values in the untracked `.env` only. Use URL-safe hex credentials or properly URL-encode them, and never commit secret values.

For security posture and deployment boundaries, see [infra/README.md](../infra/README.md) and [SECURITY.md](../SECURITY.md).

## Source review and release constraints

The documentation and local test commands are **not permission to deploy**. See
[architecture](architecture.md), [release readiness](release-readiness.md),
[genuine demo capture](demo-guide.md), [security](security-threat-model.md),
and [operator deployment](deployment.md). A successful Compose startup does not
prove the public website is serving this revision or that production firewall,
proxy-IP quotas, backups, legal terms and private data deletion are complete.
