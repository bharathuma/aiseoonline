# Verified-project website evidence assistant (development only)

This module provides a private backend question-answering service over indexed page excerpts and recorded deterministic SEO findings. **It is not a public AI audit or an authentication implementation.** The production FastAPI router is not registered; the Astro production build shows an unavailable notice. Production environment validation also refuses `AISEO_RAG_CHAT_ENABLED=true`.

## Architecture

- `rag/assistant.py`: typed questions, up to three previous user questions (not model answers), controlled retrieval, source IDs, structured draft validation, server-generated citations and uncertainty.
- `rag/chat_routes.py`: development-only REST contract, constant-time secret comparison, loopback-client restriction, server-configured development owner UUID, explicit project verification, atomic Redis rate/spending limits, and provider error handling.
- `apps/web/src/pages/internal/rag-chat.astro`: always `noindex`; a React form is hydrated only in the Astro development environment. The production build shows an unavailable notice.
- `apps/web/src/components/PrivateRagChat.tsx`: responsive questions, locally held short history, pending/error/empty states, source quotes and safe clickable URL references. No browser localStorage, cookies or private transcript persistence is added.

**Prior work is preserved:** the existing hybrid RAG retriever filters every vector and full-text query by verified `project_id`, owner, document scope and embedding model revision. This part adds a development-only way to ask questions using that service. It does not bypass the secure crawler or enable unauthenticated ingestion.

## Evidence contracts

The assistant retrieves up to four indexed excerpts using bounded hybrid search (each with its real `rag:<document_uuid>:<chunk_uuid>` source ID) and up to eight real `seo_findings` associated with pages in the latest **completed** audit for this project (with `finding:<uuid>` IDs). It only reads findings whose related page shares the same project/audit, and discards invalid or off-host URLs. No audit findings are invented if the project's database has no completed audit.

Each drafted answer contains up to four short statements. Every statement must identify a real retrieved source ID and provide a verbatim supporting quote that occurs inside that source's stored excerpt. Otherwise, the **entire answer is rejected**. Unsupported numerical or absolute sitewide claims are rejected if not present in the cited quote. The API reconstructs the final list of citations from server-owned source records, never from model-provided URLs. Different/conflicting excerpts retain separate identifiers; the model may state uncertainty but cannot silently fabricate missing records.

The answer includes an explicit scope caveat: **only collected, authorized excerpts and recorded findings are covered; it is not a complete audit**. Missing evidence returns an empty answer with an uncertainty message, rather than generating unsupported statements.

The `website_rag/v1` system template is versioned and controlled on the server. Retrieved pages, recorded findings, current questions and history are separately JSON-serialized as untrusted user-role data. No retrieved HTML is executed and no source text is promoted to trusted instructions. These safeguards mitigate prompt injection but cannot mathematically guarantee every paraphrase is factually accurate. User review remains essential.

## Development-only access

Before enabling locally, create a verified **development** user/project and index permitted content using the existing [RAG ingestion workflow](rag-ingestion.md). For SEO issue questions, add authentic deterministic findings through your own controlled audit fixture or future audit workflow; the current repository does **not** expose a complete private scan orchestration.

1. Run PostgreSQL + pgvector, Redis, the API and Astro locally using [getting started](getting-started.md). Apply Alembic migrations.
2. Generate a random access token *outside the repository* (for example, `openssl rand -hex 32`). Do not commit or share its value.
3. Configure the **backend** with `AISEO_ENVIRONMENT=development`, `AISEO_RAG_CHAT_ENABLED=true`, `AISEO_RAG_CHAT_DEV_TOKEN` (at least 32 characters), and `AISEO_RAG_CHAT_DEV_OWNER_ID` (UUID of a real verified project owner). The user/project identifiers come from your trusted local fixture setup, not from browser-claimed ownership.
4. Configure `AISEO_OPENAI_API_KEY`, `AISEO_RAG_EMBEDDING_MODEL`, `AISEO_RAG_EMBEDDING_VERSION`, `AISEO_LLM_INPUT_USD_PER_MILLION`, `AISEO_LLM_OUTPUT_USD_PER_MILLION`, and `AISEO_RAG_CHAT_EMBEDDING_USD_PER_MILLION`. **Supply actual current model prices**; the app does not invent them. Both embedding and generative model calls require credentials.
5. Open `http://127.0.0.1:4321/internal/rag-chat/`, enter the project's UUID and local development token, then ask a question.

Only loopback requests with the correct secret may use the endpoint, even when running in development. The server authorizes the project against its configured owner UUID before spending money on embedding or generating text. Credentials remain backend-only except the **explicit local development access token** the operator types into the form. That temporary token is not an OpenAI credential. Local frontend memory holds at most six exchanges, and only the most recent three user questions accompany a follow-up. Previous answers and pasted documents never become evidence.

Do not expose this local development server through a public tunnel or production reverse proxy. This temporary gate **is not suitable as a replacement for real account authentication**, durable ownership verification and per-user subscriptions.

### HTTP example

```http
POST /api/v1/internal/rag/chat
X-Dev-Rag-Token: <local-development-secret>
Content-Type: application/json

{
  "project_id": "00000000-0000-0000-0000-000000000000",
  "question": "Which indexed pages are missing meta descriptions?",
  "previous_questions": ["What SEO checks have been recorded?"]
}
```

The server returns verified statements with `source_id`, `supporting_quote`, `sources` containing real page URLs and timestamps, `uncertainty`, optional measured token usage and a scope disclaimer. No API keys, embeddings, raw provider errors or database credentials are returned. Missing/unauthorized projects return the same generic 404; incomplete configuration returns 503; denied budgets return 429.

## Cost and resource controls

The route is disabled by default and requires a functional Redis instance, model price settings, a configured API key and daily/per-request budget settings. The Lua admission gate atomically enforces at most **six requests per connecting peer per hour**, plus a separate UTC-day upper-bound allocation ledger. Every attempted generation reserves a conservative allowance for a full LLM input/output and retry envelope, plus query embedding retries, **before embedding or generating**. Failed and no-evidence attempts may consume allocation; this is intentionally conservative, not a billing invoice. Enforce OpenAI account-side spending limits as an additional control.

Defaults: daily allowance `$1`, per-request ceiling `$0.10`, LLM output capped at 480 tokens, up to four statements and 12 candidate evidence excerpts (1800-byte vector-retrieval context). Requests have a 52-second response deadline and a two-slot application semaphore, with existing provider-level timeouts and concurrency protection. The prompt-builder rejects evidence envelopes above 4500 UTF-8 bytes; the LLM adapter also enforces its configured conservative total input/output budget. No transcript is stored.

## Local test and evaluation

```sh
uv sync --project apps/api --locked --group dev
uv run --project apps/api --locked pytest apps/api/tests/test_rag_assistant.py -q
uv run --project apps/api --locked ruff check apps/api
uv run --project apps/api --locked mypy --config-file apps/api/pyproject.toml apps/api/src
pnpm check:web
pnpm build:web
pnpm e2e:web
```

The real PostgreSQL integration suite tests a verified owner and a second isolated project, inserts a permitted indexed page plus a completed SEO finding, generates an answer using **only a deterministic fixture provider**, verifies the real finding citation and attempts unauthorized cross-project retrieval. Redis integration checks the atomic per-peer/daily allocation. CI never calls paid OpenAI or third-party websites.

**Limitations:** actual private production authentication, user sessions, stored conversation threads, a full site audit ingestion pipeline, ranking claims, automatic resolution of conflicting evidence and live OpenAI response quality are not provided in this part. They require separately approved work and operational/privacy review.
