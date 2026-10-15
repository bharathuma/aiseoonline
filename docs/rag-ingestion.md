# Private RAG ingestion and vector retrieval

The RAG backend stores cleaned, permitted **single-page** crawler snapshots under verified project ownership. It is an internal Python API, **not** a public FastAPI route. No anonymous users, deep scans or cross-project retrieval are enabled.

## Structure

- `crawler/content.py` extracts bounded body sections from HTML, preferring `<main>`/`<article>` and skipping scripts, styles, navigation, header/footer chrome, forms and other excluded elements.
- `rag/chunking.py` builds deterministic, section-aware text chunks (750-character target with 90-character overlap by default), preserving section headings and SHA-256 content hashes. Defaults allow at most 24 chunks and 18,000 cleaned source characters. Invalid or oversized documents fail, rather than truncating a semantic index silently.
- `rag/embeddings.py` defines a replaceable `EmbeddingProvider` interface and a backend-only OpenAI adapter. It uses the OpenAI embeddings endpoint with `text-embedding-3-small` and `dimensions=384` by default. A clearly named local `FixtureEmbeddingProvider` is used by deterministic tests, never as a silent production fallback.
- `rag/store.py` provides idempotent ingestion, forced and version-based reindexing, ownership-scoped similarity search, and deletion. The caller owns SQLAlchemy transaction commit/rollback. Failed embedding generation happens before changing existing indexed chunks.

## Storage and migrations

Migration `0002_rag_vectors` creates `rag_documents` and `rag_chunks`, with a pgvector **384-dimensional** column, a cosine HNSW index, an additional project/document lookup index, cascading foreign keys, and tenant-matching document/chunk foreign-key constraints.

Source metadata includes the normalized URL, verified project ID, document ID, crawl timestamp, indexing timestamp, content hash, source section heading, chunk ordinal, and a provider/model/version/dimension record. A document has a unique (project, source URL) key. Reingesting the exact same content with the same embedding revision and chunk settings leaves rows unchanged. Updating content or a model/revision rebuilds the document’s chunks in a transaction. Deleting a document removes its chunks; deleting a project cascades to documents/chunks.

**Dimension compatibility:** the schema is intentionally fixed at **384 dimensions**. The OpenAI `dimensions` parameter requests that length, and both provider responses and stored vectors are checked. Model/revision metadata prevents queries from mixing incompatible semantic vector spaces. Moving to a different dimension requires a separately reviewed schema/index migration and reembedding, **not** an automatic silent conversion.

Run the migration after configuring `AISEO_DATABASE_URL` for a PostgreSQL 16 instance with the pgvector extension:

```bash
uv sync --project apps/api --locked --group dev
uv run --project apps/api --locked alembic -c apps/api/alembic.ini upgrade head
```

### Example (backend only)

Only invoke this from authenticated, authorized backend code or a verified-site job. Do not use an anonymous public endpoint. The owner/project UUIDs must come from trusted authentication, **not** arbitrary browser-supplied identifiers.

```python
from uuid import UUID
from sqlalchemy.orm import Session

from aiseoonline_api.config import Settings
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.rag.embeddings import make_openai_embedding_provider
from aiseoonline_api.rag.store import RagStore

settings = Settings()
engine = create_database_engine(settings)
provider = make_openai_embedding_provider(settings)

try:
    with Session(engine) as session, session.begin():
        store = RagStore(session, provider)
        result = store.ingest_url(
            project_id=UUID("PUT-VERIFIED-PROJECT-UUID-HERE"),
            owner_id=UUID("PUT-AUTHENTICATED-OWNER-UUID-HERE"),
            url="https://example.org/help",
        )
        print(result.action, result.chunks)
    with Session(engine) as session:
        store = RagStore(session, provider)
        matches = store.search(
            project_id=UUID("PUT-VERIFIED-PROJECT-UUID-HERE"),
            owner_id=UUID("PUT-AUTHENTICATED-OWNER-UUID-HERE"),
            query="ceramic planter maintenance",
            limit=5,
        )
        for hit in matches:
            print(hit.source_url, hit.section_heading, hit.similarity)
finally:
    provider.close()
    engine.dispose()
```

The example UUID placeholders must be replaced with real authenticated identifiers. Calling `ingest_url` verifies project ownership and `verification_status='verified'` **before any network connection**, then uses the existing robots-aware, same-origin, DNS/IP-restricted, one-page crawler. A provided `PageSnapshot` is accepted only through internal trusted call sites and receives the same project/domain and status checks. A new public ingestion route is intentionally **not provided**.

## Limits and failures

- A single allowed page per fetch; no authentication bypass, recursive crawl, rendered JavaScript, or arbitrary redirect following.
- At most 24 chunks, 384 floats per embedding, 8 strings per embedding request and 2,000 characters per item; embedding provider retries at most twice on transient errors and has a network timeout.
- The embedding API key is read from backend `AISEO_OPENAI_API_KEY` and is not logged or exposed in the browser. Without credentials, the provider factory raises `CredentialsUnavailable`.
- The embedding model and revision are controlled by `AISEO_RAG_EMBEDDING_MODEL` and `AISEO_RAG_EMBEDDING_VERSION`. Revision strings are **application configuration labels**, not authoritative statements about a provider's deployed weights; explicitly increment them when changing representation.
- Retrieved content remains untrusted and must later be quoted as evidence, never executed as an instruction. Access checks require verified project ownership for every operation. Do not expose private vectors, raw source excerpts, or query results to unauthenticated users.
- RAG data is stored as extracted text, so it may contain user-provided material. Operational access, data retention and deletion policy must be reviewed before production.

## Verification

Offline tests contain no paid requests and use only controlled HTML fixtures:

```bash
uv run --project apps/api --locked pytest apps/api/tests/test_rag.py -q
```

The real pgvector test (in CI, against the local PostgreSQL service) verifies the extension and HNSW index, inserts a verified sample document, searches by cosine similarity, proves idempotence, changes the source, reindexes for a different embedding revision, rejects cross-project access, deletes documents and confirms cascades.

```bash
AISEO_TEST_DATABASE_URL=postgresql+psycopg://... uv run --project apps/api --locked pytest apps/api/tests/test_rag_integration.py -q
```

This does not claim live OpenAI embedding API compatibility or actual production throughput. Live provider calls require explicit approval and billing settings; they are deliberately absent from CI.
