# Private, durable audit execution

The internal SEO audit runner uses Celery/Redis to process bounded, owner-verified **single-page** jobs and PostgreSQL as the durable source of truth. The LangGraph graph uses its supported PostgreSQL checkpoint backend. A responsive, **noindex** development UI at `/internal/audit/` offers local-only progress polling, cancellation, results, and JSON/CSV/HTML downloads.

**Scope:** There is still no general account login and no supported production audit API. All routes are restricted to development/test localhost with a configured 32+ character development token and a server-bound owner UUID. They are not mounted in production, even if an incorrect proxy forwards an API request. The public `/audit/` page still correctly advertises the service as not publicly available. No deep scans or remote execution are enabled.

## Operating requirements

- PostgreSQL 16 + pgvector, Redis 7, API process, Celery worker, and **Celery Beat** as a separate process.
- Apply Alembic migration `0004_audit_execution`, which extends existing `audit_jobs` with owner, URL, request, idempotency key, steps, progress, leases, attempts, timestamps, cancellation flag, and validated report JSON. Structured technical issues also save their severity, affected URL, correction, and evidence reference to `seo_findings`. AI recommendations remain a distinct field in the report JSON and are never labeled as deterministic findings.
- Install the supported `langgraph-checkpoint-postgres` dependency with the committed `uv.lock`. The worker initializes the PostgreSQL checkpointer with `await checkpointer.setup()`; a deterministic per-job thread ID is derived from the job UUID.
- Set `AISEO_AUDIT_JOBS_ENABLED=true` only in local development or an isolated test environment. Set `AISEO_AUDIT_DEV_OWNER_ID` to an actual **verified project owner** UUID and `AISEO_AUDIT_DEV_TOKEN` to a 32+ character ASCII random value.
- Configure `AISEO_DATABASE_URL`, `AISEO_REDIS_URL`, `AISEO_OPENAI_API_KEY`, **both** real model price rates `AISEO_LLM_INPUT_USD_PER_MILLION` and `AISEO_LLM_OUTPUT_USD_PER_MILLION`, and the audited model choice. Without any of these, jobs cannot be scheduled.
- Set optional conservative limits `AISEO_AUDIT_DAILY_JOB_CAP=12`, `AISEO_AUDIT_REQUEST_USD_CAP=0.10`, `AISEO_AUDIT_DAILY_USD_CAP=1.00` (USD). These are preallocated retry envelopes, **not** measured provider invoices or actual financial limits on your OpenAI account.

Start worker and beat separately after migrations:

```bash
uv sync --project apps/api --locked --group dev
uv run --project apps/api alembic -c apps/api/alembic.ini upgrade head
PYTHONPATH=apps/worker uv run --project apps/api celery -A run:celery_app worker --loglevel=INFO
PYTHONPATH=apps/worker uv run --project apps/api celery -A run:celery_app beat --loglevel=INFO
```

Make localhost-only API requests with `x-dev-audit-token`; the owner UUID is **never** accepted in the request body:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/internal/audits \
  -H "x-dev-audit-token: $AISEO_AUDIT_DEV_TOKEN" \
  -H 'Idempotency-Key: local-example-20261015-a' \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"REPLACE-WITH-VERIFIED-PROJECT-UUID","url":"https://example.org/article"}'
```

The response contains the job UUID, status, current step, percentage and attempts. Poll `GET /api/v1/internal/audits/{id}`; cancel with `POST /api/v1/internal/audits/{id}/cancel`. Once `report_ready=true`, fetch `/{id}/report`, `/{id}/report.csv`, or `/{id}/report.html`. All require the same token and re-check project ownership. The HTML export uses escaped content and a restrictive Content Security Policy. CSV export protects leading spreadsheet formula characters. No export is shared via public URL.

## Job semantics and recovery

- The client supplies an ASCII 8–96 character `Idempotency-Key`. Its uniqueness is **enforced by PostgreSQL** per project. Identical submissions return the same job; using the key with different inputs returns a conflict.
- A job is inserted and budget allocation is reserved before the queue dispatch. If Redis publishing fails after PostgreSQL commit, the job remains queued and a periodic recovery sweep retries it; the client may retry with the **same** idempotency key.
- The worker obtains a locked claim and an attempt generation number. A second Celery delivery cannot execute while another healthy lease is active. A heartbeat keeps the lease alive. A late/stale worker cannot overwrite a newer attempt or a cancelled job.
- Celery Beat sends a recovery sweep roughly every 15 seconds. Expired work is requeued, subject to a maximum of three attempts and the original execution deadline. A missing Beat process means orphan recovery is **not** available; it must be supervised.
- The audited graph checkpoints each completed node to PostgreSQL under `thread_id=audit:<job_uuid>`. A retry rechecks owner authorization and resumes from the last checkpoint. A provider call interrupted **between** billing and checkpoint persistence may be charged again. The reservation conservatively includes three possible worker attempts and all provider retries, but it is **not** exactly-once billing.
- Limits: one permitted page, at most two tool selections, three graph model calls, maximum 45 seconds of actual job wall time from its **first** start, separate provider timeouts, 15-second recovery sweeps, bounded attempts and financial allocation. Unverified projects are rejected **before any crawler or model call**.
- A cancellation flag is checked at graph node boundaries; the worker will stop at the next check. If a slow external API call is in progress, it may finish before cancellation is honored. Late results are discarded once cancelled. A timeout, invalid provider response, unverified project or exhausted attempts ends with a safe terminal status. The UI does not expose raw exception text, prompts, crawl content, stack traces or secrets.
- A failed crawler node returns a clearly labeled **partial** report with no invented page findings. A downstream tool/model failure preserves the already collected deterministic issues as a partial report. The agent currently processes a single page, so sitewide partial-page continuation is **not claimed**.

## Separation of observed evidence and AI output

`AuditReport.findings` contains deterministic rule IDs, severity, URL, summary, observed quote, source reference and correction. `AuditReport.recommendations` contains distinct AI interpretations tied to existing findings and exact supporting quotes; `requires_human_approval=true` and `action_executed=false` are enforced by Pydantic. Report exports preserve that distinction.

Website HTML and checkpoint rows can contain sensitive crawl evidence. Restrict DB backups, access roles, audit logs and retention policy. Redis is used for queueing and cost-control counters, not as the report source of truth. Configure backup/retention and checkpoint cleanup before any real client deployment. In addition to the application budgets, set provider-side spending limits and alerts.

## Testing and limitations

```bash
uv run --project apps/api --locked pytest apps/api/tests/test_audit_execution.py -q
AISEO_TEST_DATABASE_URL=postgresql+psycopg://... \
  uv run --project apps/api --locked pytest apps/api/tests/test_audit_jobs_integration.py -q
pnpm test:web
pnpm check:web
pnpm build:web
pnpm e2e:web
```

Integration tests use local PostgreSQL, Redis, deterministic HTML snapshots and fixture model outputs. They exercise status transitions, idempotency, cancellation, lease expiry, abandoned work, owner isolation, report storage, duplicate Celery delivery and PostgreSQL LangGraph checkpoint recovery. No external crawling or paid OpenAI calls run during CI. These tests do **not** establish live-provider billing correctness, production-scale concurrency, or guaranteed recovery from every conceivable operating-system failure.

No deployment, billing changes, or PR merge occurs as part of this implementation.
