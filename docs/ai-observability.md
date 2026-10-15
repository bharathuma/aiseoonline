# Privacy-safe AI observability and spending reservations

## Scope and trust boundary

This is opt-in server-side observability for the API, OpenAI-compatible provider and
development-only verified-owner audit workflow. Production audit access remains **disabled**
by the existing authorization and environment guards. This part does not enable deep scans,
public authentication, real-time billing reconciliation, or deployment.

The API creates its own random request ID and trace context; client-supplied IDs or
`traceparent` are not trusted. At audit creation a sampled W3C trace parent and random
request ID are written to PostgreSQL. A recovered Celery worker restores that parent
before entering the graph, so worker, graph-node, tool and model spans share one trace
across process boundaries and retry attempts. The trace parent contains identifiers
only, never HTTP headers or credentials.

### Supported exporters (both optional)

- **OpenTelemetry OTLP/HTTP JSON:** `AISEO_OTEL_TRACES_ENDPOINT=https://collector.example/v1/traces`.
- **Langfuse v4 OTLP ingestion:** set all three `AISEO_LANGFUSE_HOST=https://cloud.langfuse.com`,
  `AISEO_LANGFUSE_PUBLIC_KEY`, `AISEO_LANGFUSE_SECRET_KEY`. The exporter uses
  `POST /api/public/otel/v1/traces`, HTTP Basic authentication and
  `x-langfuse-ingestion-version: 4`. Use the correct regional or self-hosted HTTPS host.
- These settings are off by default, and **no tracing data leaves the application** unless
  an endpoint is configured. Invalid/incomplete settings fail configuration validation.
- This implementation writes standard OTLP/HTTP JSON directly with existing `httpx` and
  does not install the Langfuse Python SDK or the OpenTelemetry SDK. It therefore does
  **not** claim automatic instrumentation for arbitrary third-party library internals.
  API entry, Celery audit execution, graph steps, tool execution and direct provider calls
  are instrumented explicitly.
- A bounded in-memory queue (256 spans per process) avoids waiting for external telemetry
  hosts during requests. HTTP redirects and ambient proxy credentials are disabled, and
  exporter timeouts are 1 second. Export failures log `observability_export_failed`
  without response bodies, secrets, or hostnames. Queue saturation logs
  `observability_queue_full`. Alert on either log message and monitor the collector's
  own ingestion/drop counters. If the process dies, queued spans may be lost.
  Telemetry delivery is **best effort, not durable**, and does not block audit completion.
- Restrict configured exporters to trusted destinations. Exported metadata includes only
  allowlisted safe identifiers and numeric usage/latency values. The allowlist explicitly
  excludes prompts, rendered output, page content, URLs, request/response bodies, headers,
  emails, names, authentication material, and raw exception text.
- Logs and exporters remain independent of the PostgreSQL reports and must not alter
  deterministic SEO findings or AI interpretations.

## Correlation and metrics

`http.request` (server request ID) → `audit.job` (job ID and attempt) →
`audit.node` → `audit.tool` or `ai.generate` / `ai.stream`.

Each completed model invocation reports the model name, safe prompt-template identifier,
provider-reported input/output/total tokens, retry count (where available),
duration in milliseconds, and `estimated_cost_usd` **only** if the operator configured
model pricing. Langfuse generation observations additionally receive standardized
`gen_ai.request.model` and `gen_ai.usage.input_tokens` /
`gen_ai.usage.output_tokens` attributes. Inputs and outputs are intentionally absent
from exported spans.

`estimated_cost_usd` uses
`(input_tokens × AISEO_LLM_INPUT_USD_PER_MILLION +
output_tokens × AISEO_LLM_OUTPUT_USD_PER_MILLION) / 1,000,000`.
The pricing rates are **operator-supplied assumptions** and not verified against the
provider's invoices. Token counts are from the actual provider response; failed,
interrupted, or improperly terminated calls may have unknown billed usage.
Retries can be charged even if no final usage is returned. Streaming spans are emitted
at stream termination; partial streams with no usage are explicitly not counted as zero.

The audit report retains the existing aggregate successful-model `token_usage` and
structured technical findings independently of optional tracing.

## Atomic budget reservations

- Existing per-audit request envelope `AISEO_AUDIT_REQUEST_USD_CAP` is checked
  before scheduling. It covers worst-case configured retries and attempts.
- `AISEO_AUDIT_OWNER_DAILY_USD_CAP` (default USD 0.50) caps **estimated reservations**
  for a verified audit owner in a UTC day.
- Existing `AISEO_AUDIT_DAILY_USD_CAP` (default USD 1.00) and
  `AISEO_AI_META_DAILY_USD_CAP` (default USD 2.00) remain independent operation caps.
- `AISEO_AI_GLOBAL_DAILY_USD_CAP` (default USD 3.00) is atomically shared by the
  audited single-page jobs, verified-owner private RAG chat, and public AI metadata generator. Lua scripts reserve
  the owner, operation and global counters together in Redis. Exhaustion returns the
  existing rate-limit or budget error, and Redis failures are **fail closed**.
- Public anonymous AI meta suggestions have per-peer rate limits rather than a
  user account, so the owner cap only applies to authenticated/verified audit jobs.
  Account-level budgets for any future public user system are not yet implemented.
- These are **pre-call spending reservations**, not invoice-accurate ledgers or
  refunds. Reservations are not released when jobs fail or cached calls succeed
  after acquisition. OpenAI provider-side billing caps and alerts should also be set.

## Dashboards and alerts

In Langfuse, use the trace ID to find a full agent execution and inspect the
`generation` observations grouped by model and token usage. Filter observation
attributes for `job_id` and inspect `audit.node`/ `audit.tool` timings.
An OTLP-compatible collector can route the same traces to Jaeger, Tempo or a
managed APM for latency/error-rate dashboards. Suggested panels: 95th-percentile
model and audit duration, generation error percentage, retry count, token totals
per model, sum of *estimated* USD per model, failed-export and dropped-span log
counts. Alert on budget rejections, `observability_export_failed`, and
`observability_queue_full`. These are configuration instructions, not a claim that
a hosted dashboard or alert was provisioned.

**Security:** raw audit checkpoints/reports remain in PostgreSQL under verified ownership.
Monitoring destinations and logs must use controlled access and short retention.

## Verification

Run locked API tests, mypy and Ruff; real PostgreSQL + Redis integration tests exercise
shared budget keys and durable job recovery. New offline tests validate W3C trace
propagation, OTLP/Langfuse payloads, allowlist redaction and real mocked HTTP provider
usage. They do **not** verify live Langfuse uptime, exporter networking to a paid tenant,
provider invoices, or reliability under an abrupt process crash.

References:
- https://langfuse.com/integrations/native/opentelemetry
- https://langfuse.com/integrations/native/opentelemetry/migration-to-v4
- https://opentelemetry.io/docs/specs/otlp/
