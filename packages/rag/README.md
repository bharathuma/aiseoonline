# Retrieval and ingestion

The executable private RAG foundation lives in [the API package](../../apps/api/src/aiseoonline_api/rag/).
It includes bounded cleaned HTML sections, deterministic section-aware chunking, a replaceable embedding
provider, and project-scoped PostgreSQL/pgvector storage.

See [RAG ingestion and search](../../docs/rag-ingestion.md) for migration steps, API examples,
security boundaries, limits, and integration tests. No public RAG endpoint or unverified deep
crawling is enabled.
