# API

Install and run the FastAPI backend using uv from the repository root:

```bash
uv sync --project apps/api --group dev
uv run --project apps/api uvicorn aiseoonline_api.main:app --reload --host 127.0.0.1 --port 8000
```

Routes:
- `GET /api/v1/health` — liveness, does not depend on external storage.
- `GET /api/v1/ready` — readiness, tests PostgreSQL and Redis; returns 503 if unavailable.
- `/api/docs` and `/api/v1/openapi.json` — API documentation.

`AISEO_DATABASE_URL` is required for Alembic migrations. `AISEO_REDIS_URL` is required for Celery jobs; OpenAI credentials remain optional. Production settings require both storage URLs. Runtime settings use the `AISEO_` prefix and redact SecretStr fields from their representations.

From the root, apply migrations with `uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head`. The initial revision creates six SQL tables and requires PostgreSQL with pgvector available. A bundled development stack is in `compose.yaml`; see [getting started](../../docs/getting-started.md).
