# API conventions

API endpoints use the `/api/v1/` prefix. The OpenAPI document is available at `/api/v1/openapi.json` and Swagger UI at `/api/docs`.

## Success responses

Endpoints use Pydantic response models. Existing endpoints intentionally retain their original response shapes:

- `GET /api/v1/health` responds with `status`, `service` and `version`, regardless of external service availability.
- `GET /api/v1/ready` responds with the state of PostgreSQL and Redis; it uses HTTP 503 and a structured readiness response when dependencies are unavailable.

No SEO analysis endpoints have been published yet. Business endpoints will define their own typed result models.

## Error responses

Request validation, missing routes, disallowed methods, standard HTTP errors and unhandled failures use the same JSON envelope:

```json
{
  "error": {
    "code": "validation_error",
    "message": "One or more request fields are invalid.",
    "details": [
      { "field": "body.size", "issue": "greater_than" }
    ]
  },
  "request_id": "0123456789abcdef0123456789abcdef"
}
```

The example request ID is illustrative. Every HTTP response includes a new server-generated `X-Request-ID` header. Client-provided IDs are ignored.

Validation details contain field paths and safe machine-readable error types, **not** rejected values, error-stack traces, API keys or request bodies. Detailed internal failures are never exposed in production error bodies. The operational `/ready` response is a deliberate exception to the generic error envelope, preserving a simple health-check contract.

| Code | HTTP status | Meaning |
| --- | ---: | --- |
| `bad_request` | 400 | Request cannot be processed |
| `not_found` | 404 | No matching resource |
| `method_not_allowed` | 405 | Unsupported HTTP method |
| `validation_error` | 422 | Invalid or missing input |
| `rate_limited` | 429 | Request rate exceeded (reserved for later endpoints) |
| `internal_error` | 500 | Unexpected server failure |
| `service_unavailable` | 503 | Service temporarily unavailable |

Requests are not logged with URL query strings, authorization headers or bodies. A log filter removes common credential patterns as a secondary protection, not a replacement for avoiding sensitive logs.

## Local verification

```bash
uv run --project apps/api pytest apps/api/tests -q
uv run --project apps/api ruff check apps/api
uv run --project apps/api mypy apps/api/src
```

Tests include an isolated fixture router to verify validation failures and unexpected exceptions. These test-only endpoints are **not included** in the shipped API.
