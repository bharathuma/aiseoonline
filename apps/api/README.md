# API

FastAPI service for AISEOOnline. The versioned HTTP API currently exposes liveness and dependency readiness checks. SEO tool endpoints are not implemented yet.

## Local commands

From the repository root:

```bash
uv sync --project apps/api --group dev
uv run --project apps/api uvicorn aiseoonline_api.main:app --reload --no-access-log
uv run --project apps/api pytest apps/api/tests -q
uv run --project apps/api ruff check apps/api
uv run --project apps/api mypy apps/api/src
```

Documentation: `/api/docs` · OpenAPI: `/api/v1/openapi.json`.

Errors use a consistent JSON format:

```json
{
  "error": {
    "code": "validation_error",
    "message": "One or more request fields are invalid.",
    "details": [{"field": "body.size", "issue": "greater_than"}]
  },
  "request_id": "0123456789abcdef0123456789abcdef"
}
```

The ID above is illustrative. Every response includes a random server-generated `X-Request-ID`, and arbitrary exception details are not returned to callers. Successful health responses remain backward compatible. See [API contracts](../../docs/api-contracts.md).
