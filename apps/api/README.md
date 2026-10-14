# API

FastAPI backend for AISEOOnline. Only the versioned health endpoint is implemented.

From the repository root:

```bash
uv sync --project apps/api --group dev
uv run --project apps/api uvicorn aiseoonline_api.main:app --reload --port 8000
```

- Health: http://127.0.0.1:8000/api/v1/health
- API docs: http://127.0.0.1:8000/api/docs
- OpenAPI: http://127.0.0.1:8000/api/v1/openapi.json

Run tests:

```bash
uv run --project apps/api pytest apps/api/tests -q
```

Configuration uses `AISEO_`-prefixed environment variables. See the root `.env.example`. No model credentials, database, or other services are required for the health endpoint.
