# ADR 0003: PostgreSQL and pgvector

**Status:** Accepted; not implemented.

## Context

Projects, crawl jobs, findings, and reports are relational data. The planned assistant also needs semantic search over indexed documents.

## Decision

Use PostgreSQL as the primary database, Alembic for migrations, and pgvector for embedding similarity. Use PostgreSQL full-text search for keyword retrieval.

## Alternatives

A separate vector database adds deployment and synchronization needs. SQLite is convenient locally but is not the preferred store for the intended multi-user application.

## Consequences

Vector dimensions, embedding versions, filtering, indexing, and retrieval performance will need explicit handling. Access checks must restrict every query to permitted project content.
