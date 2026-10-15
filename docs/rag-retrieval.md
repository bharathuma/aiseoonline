# Private hybrid retrieval

AISEOOnline retrieves **previously ingested and authorized project evidence** using PostgreSQL full-text search and pgvector cosine similarity. This is an internal backend service. It does **not** create a public search endpoint, trigger a website crawl, call a generative LLM, or expose private website content to anonymous users.

## Architecture and migration

Alembic revision `0003_rag_fulltext` extends `rag_documents` with `document_type` (`web_page`, `guide`, `reference`) and `access_scope`, initially and exclusively `owner_only`. A database CHECK constraint explicitly disallows wider access scopes until a separately reviewed authorization model exists. Existing rows migrate as `web_page` and `owner_only`. It adds a PostgreSQL **GIN** expression index over `to_tsvector('english'::regconfig, coalesce(heading,'') || ' ' || text)`, plus a project/type/scope lookup index.

The previous 384-dimensional HNSW cosine index and embeddings remain unchanged. Keyword queries use `plainto_tsquery('english'::regconfig, :query)`, which treats user text as data rather than executable tsquery syntax. Ranking uses `ts_rank_cd` and cannot substitute fabricated evidence. All SQL is bound through SQLAlchemy. Only previously indexed real chunk rows may be returned.

Every search first verifies `project_id` and `owner_id` belong to a **verified** project. Both vector and keyword SQL apply project ID, owner ID, verified status, owner-only access, permitted document types, and embedding provider/model/version/dimension filters. Optional `max_age_days` limits the snapshot capture timestamp. Unauthorized requests fail **before** computing a paid embedding or running search SQL.

## Search modes

`HybridRetriever.retrieve()` supports `semantic`, `keyword` and `hybrid`:

- **Semantic:** one query embedding, cosine distance via pgvector, bounded nearest-neighbor candidates. Minimum cosine similarity defaults to **0.35**; low-similarity items are rejected.
- **Keyword:** indexed full-text query and coverage rank, bounded matching candidates. Empty/no-match queries return an empty result. **No query embedding is generated** in keyword-only mode.
- **Hybrid:** takes both lists of up to `candidate_k` hits, combines by reciprocal rank fusion (RRF), then applies the same evidence and budget controls.

For each chunk `d` and rankings `V` (vector) and `K` (keyword):

`RRF(d) = sum(1 / (rrf_k + rank(d, ranking)))`, for each ranking in which `d` appears, with 1-indexed ranks. Default `rrf_k=60`. Chunks found by both methods gain evidence from both lists, but the RRF score **is not a probability or relevance guarantee**. The minimum RRF score, default `0.015`, rejects weak/unranked candidates. Ties break deterministically by chunk UUID. Scores are not normalized across different retrieval modes.

Optionally inject a `Reranker` implementation with `reorder(query, candidates)`. Its output must be an **exact permutation of already retrieved chunk IDs**: fabricated IDs, repeats or dropped items raise an error. No paid reranker is installed or enabled. A future externally hosted reranker would require a separate privacy/security and cost review.

## Citation-ready, bounded evidence

Each `RetrievedEvidence` includes actual chunk text and document type, owner-only access scope, fused score, channel-specific ranks and positions, plus a `Citation` object with:

- `source_id = rag:<document UUID>:<chunk UUID>`
- owner-authorized project UUID, document UUID, chunk UUID, original normalized URL
- extracted section heading, SHA-256 content hash and crawl capture timestamp

These IDs and URLs come **directly from stored database rows**, not an LLM. Idempotent ingestion preserves citations; reindexing or updating may create new chunk IDs. Consumers must verify source IDs belong to the result set before quoting them, and should not mistake the citation for independent verification of factual accuracy.

Identical chunk hashes across pages are deduplicated, preserving a real first-ranked citation rather than printing redundant paragraphs. Freshness filtering drops old snapshots. Contradictory excerpts, when present, remain distinct and attributed to their actual source; this system **does not resolve competing claims, prefer a newer fact as a universal truth, or synthesize a consensus**. Downstream agents should disclose disagreements and seek corroboration. For an irrelevant query, returning an empty result is preferable to filling the token budget with weak matches.

`top_k` is 1–10; `candidate_k` is 5–50, and must be at least `top_k`. `max_context_tokens` is 200–12,000 and currently uses the **conservative UTF-8 byte count** of each excerpt, URL and heading, rather than an exact model tokenizer. That count is clearly identified as `utf8_bytes_upper_bound`. Whole sources that do not fit are skipped, not silently truncated into fake citations. The downstream generation service must still enforce its **own tokenizer-specific context and cost budgets**.

## Backend example

Call this only from already authorized server-side workflows. The owner UUID must be resolved from trusted authentication rather than directly trusted from a browser payload:

```python
from uuid import UUID
from sqlalchemy.orm import Session

from aiseoonline_api.config import Settings
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.rag.embeddings import make_openai_embedding_provider
from aiseoonline_api.rag.retrieval import HybridRetriever, RetrievalOptions

settings = Settings()
engine = create_database_engine(settings)
provider = make_openai_embedding_provider(settings)

try:
    with Session(engine) as session:
        report = HybridRetriever(session, provider).retrieve(
            owner_id=UUID("REPLACE-WITH-AUTHENTICATED-OWNER-UUID"),
            project_id=UUID("REPLACE-WITH-VERIFIED-PROJECT-UUID"),
            query="ceramic planter watering",
            options=RetrievalOptions(
                mode="hybrid", top_k=5, candidate_k=20,
                document_types=("web_page", "guide"),
                max_age_days=180, max_context_tokens=2400,
            ),
        )
        for hit in report.hits:
            print(hit.citation.source_id, hit.citation.source_url)
finally:
    provider.close()
    engine.dispose()
```

For local development, apply migrations with the [RAG ingestion setup](rag-ingestion.md) using PostgreSQL 16 + pgvector.

## Repeatable evaluation

The versioned synthetic dataset `apps/api/tests/fixtures/rag_retrieval_v1.json` contains **five** labeled fixture documents and **four** known-answer queries. It uses no external crawl or paid API calls. `test_rag_retrieval_integration.py` ingests all documents into a real PostgreSQL+pgvector database using the explicitly named deterministic fixture embedding provider, executes hybrid search, checks relevance labels, and calculates:

- **Recall@3:** fraction of test questions for which at least one labeled relevant document appears within the first three distinct retrieved results.
- **MRR@3:** mean reciprocal rank (1/rank) of the first labeled relevant document in the first three, or 0 if absent.

The test requires Recall@3 ≥ 0.75 and MRR@3 ≥ 0.50, in addition to explicit checks for live FTS index, semantic/keyword modes, tenant isolation, type/freshness filters, duplicate removal, rerank safety, negative queries and citation metadata. **These are deterministic fixture acceptance thresholds, not production performance claims or benchmarks of live OpenAI embeddings.** The test corpus is small and intentionally easy; realistic judgments, multilingual cases, larger corpora, privacy auditing, and precision/latency evaluation remain necessary before production.

To run:

```bash
uv sync --project apps/api --locked --group dev
uv run --project apps/api --locked alembic -c apps/api/alembic.ini upgrade head
AISEO_TEST_DATABASE_URL=postgresql+psycopg://... \
  uv run --project apps/api --locked pytest apps/api/tests/test_rag_retrieval_integration.py -q
uv run --project apps/api --locked pytest apps/api/tests/test_rag_retrieval.py -q
```

Never run this corpus against a production tenant. Integration tests use controlled PostgreSQL containers and roll back their inserted rows; no third-party requests occur. No public endpoint, merge, billing change or deployment is part of this work.
