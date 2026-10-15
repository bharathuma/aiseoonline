# Engineering interview walkthrough

Use this as a **technical discussion aid**, not a claim of production scale.
Present code paths, decisions and test evidence, then acknowledge what is still
development-only or not independently measured.

## 1. System architecture

**Question: Why Astro plus React rather than an all-client React app?**

Answer: Static Astro pages give each tool an HTML document, canonical URL, headings
and explanatory content before hydration. React is reserved for forms and stateful
results. FastAPI handles typed validation and evidence extraction; Nginx proxies
same-origin requests and can cache only fingerprinted assets. Verify this in
`apps/web/src/pages/tools/[slug].astro`, `ToolDetail.astro`, and
`infra/nginx.web.conf`. The build report measures **uncompressed aggregate** JS
size, not per-page transferred bytes.

**Question: Why PostgreSQL + pgvector and Redis?**

Answer: PostgreSQL stores relational identity, scoped website projects, audit
records and citations with transactional consistency, plus HNSW vectors and GIN
full-text retrieval. Redis is for atomic distributed admission/budgets and Celery
transport, not permanent customer records. Alembic owns schema migrations.

## 2. LangGraph versus a fixed pipeline

**Question: Is this a real agent?**

Answer: Yes, in **development/test scope**: `agents/workflow.py` compiles a
`StateGraph` with conditional selection/execution loops. A Pydantic
`ToolChoice` must reference a currently permitted read-only LangChain
`StructuredTool`. It cannot arbitrarily browse or modify sites. Per-request
limits bound tools, model calls, seconds and graph recursion. If authorization
fails, it never fetches; if the provider fails, deterministic findings remain and
the report is marked partial. In production, audit routes are absent.

**Question: How is durable recovery handled?**

Answer: PostgreSQL persists jobs, leases, idempotency and progress; Celery
executes and recovers work while LangGraph stores checkpoints. Tests cover job
ownership, cancellation and failure recovery. An incomplete checkpoint/backup
purge is a production privacy blocker, not a solved detail.

## 3. Retrieval-augmented generation

**Question: How does hybrid retrieval work?**

Answer: Ingestion extracts permitted text into section-aware chunks with
embedding revision metadata. A verified-owner/project filter applies before
retrieval. PostgreSQL lexical candidate ranking (full-text GIN) and pgvector
similarity candidate ranking are merged through reciprocal rank fusion (RRF).
Optional rerankers are behind an explicit interface; results include a stable
source pointer and bounded excerpt. The offline 4-case RRF test uses **supplied**
ranked candidates and is not an end-to-end corpus recall benchmark.

**Question: How is hallucination prevented?**

Answer: It is **reduced, not eliminated**. `rag/assistant.py` checks that answer
citations exist and quoted spans occur in source documents, plus bounded numeric
and universal claim checks. A synthetic contradictory sentence nevertheless
passed the semantic guard. Until independently validated semantic entailment is
implemented, do not claim factual correctness or unsupervised publishing.

## 4. LLM costs and graceful failure

**Question: How are paid model calls controlled?**

Answer: A replaceable provider interface enables deterministic scripted tests
and an optional OpenAI-backed path. Pydantic enforces output contracts, while
input/output token caps, model timeout, retry limits, Redis spend reservations
and concurrency slots constrain exposure. Configured per-million-token rates
are **operator-supplied estimates**, not reconciled invoices. Without required
credentials or pricing, the API returns explicit service errors, not invented
suggestions. See `ai_core/meta_routes.py` and `docs/llm-provider.md`.

## 5. Security and multi-tenancy

**Question: How do you prevent SSRF?**

Answer: URL syntax and schemes are restricted, DNS answers are checked, IP
destinations are publicly routable, sockets connect to validated addresses,
TLS verifies host identity, and redirect destinations are revalidated.
Runtime, byte and concurrency limits apply. **Application validation is not
an outbound firewall.** Cloud metadata/private-network egress denial and
trusted proxy identity must be configured at the host/VPC before public release.

**Question: How is tenant data isolated?**

Answer: Password sessions use salted scrypt and hashed opaque tokens;
CSRF/origin checks protect mutations. Project operations query by authenticated
owner ID, and a random proof file under
`/.well-known/aiseoonline-verification.txt` establishes domain control.
Private retrieval queries also scope to a verified project. Test fixtures
exercise unauthorized access and owner separation. Production self-registration,
email verification/recovery and privately authenticated agent routes are still
not live.

**Question: How do you handle prompt injection?**

Answer: Treat crawled content as untrusted data, never system instructions;
allowlist read-only tools, restrict model output contracts, validate references,
reject unsupported numbers, and never automatically execute website mutations.
This reduces the blast radius but cannot prove prompt injection impossible.

## 6. Observability, privacy and operations

**Question: Can you trace an audit across API and worker?**

Answer: The API creates a trusted request ID and sampled traceparent, persists
identifiers in a job, and restores context on worker recovery. Allowlisted
attributes and sanitized outcomes are sent through an optional OTLP/HTTP
exporter (including Langfuse-compatible ingestion), disabled by default.
No raw page text, URLs, prompts, tokens or model response bodies should enter
exported spans. Tests validate exporter formatting and privacy.

**Question: What would you scale first?**

Answer: Measure real ingress distribution and Core Web Vitals first. Then enforce
edge per-visitor quotas behind a **trusted** proxy, limit outbound network
connections, bound concurrency per tenant, separate DB bootstrap/migration
roles from runtime roles, and expand queues/workers only after tracking
backpressure and actual P95/queue wait. Use expand-contract migrations,
PITR backups, restore drills and measurable SLOs. Existing load tests use
synthetic 25 ms fetch delays, not real throughput.

## 7. Evaluation and prioritization

**Question: What benchmark result can you stand behind?**

Answer: The checked-in, deterministic suite exercises 18 synthetic expectations;
17 matched and one RAG semantic contradiction was falsely accepted. The failed
case remains published. This is **not** 94% model accuracy, live retrieval
recall or search quality. Reproduce with `python -m aiseoonline_api.evaluation`
in the locked API environment and compare fixture SHA-256.

**Question: What is the greatest remaining engineering risk?**

Answer: Production release gates, not more features: server/cloud egress
policy, trusted visitor-IP quota attribution, least-privilege DB roles,
confidential support/retention, and end-to-end session authorization for the
private job/RAG workflows. Keep those production routes disabled until proven.

## Suggested live code tour

1. `apps/web/src/components/toolCatalog.ts` and `ToolDetail.astro` — ten actual pages.
2. `apps/api/src/aiseoonline_api/public_tools/routes.py` and `crawler/` — bounded public checks.
3. `apps/api/src/aiseoonline_api/agents/workflow.py` — conditional graph.
4. `apps/api/src/aiseoonline_api/rag/retrieval.py` — owner-scoped RRF.
5. `apps/api/src/aiseoonline_api/agents/execution.py` — durable jobs/cost allocation.
6. `apps/api/src/aiseoonline_api/observability.py` — trace propagation and sanitization.
7. `apps/api/src/aiseoonline_api/evaluation.py` — reproducible recorded failure.
8. `docs/release-readiness.md` — clear distinction between verified test scope and the real release gates.
