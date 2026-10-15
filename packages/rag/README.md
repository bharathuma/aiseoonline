# Retrieval and ingestion

The executable private RAG foundation lives in [the API package](../../apps/api/src/aiseoonline_api/rag/).
It includes bounded cleaned HTML sections, deterministic section-aware chunking, a replaceable embedding
provider, and project-scoped PostgreSQL/pgvector storage, plus bounded full-text/vector hybrid search and citation-ready retrieval.

See [hybrid retrieval and evaluation](../../docs/rag-retrieval.md) and [RAG ingestion](../../docs/rag-ingestion.md) for migration steps, API examples,
security boundaries, limits, and integration tests. No public RAG endpoint or unverified deep
crawling is enabled.
