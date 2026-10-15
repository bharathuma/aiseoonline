# Changelog

## Unreleased

- Added a development-only, verified-owner website RAG assistant with source-quote validation, bounded follow-up questions, Redis spending limits, and a private, noindex React chat page.
- Kept private chat absent from production routes while permanent authentication and audit pipelines remain planned.

- Added verified-owner hybrid retrieval with PostgreSQL GIN full-text search, pgvector cosine similarity, reciprocal rank fusion, document-type and freshness filters, bounded citation-ready evidence, and an opt-in reranker interface.
- Added a versioned local retrieval evaluation dataset and real PostgreSQL isolation and accuracy tests.

- Added verified-project RAG ingestion with cleaned article text, section-aware chunks, explicit embedding revisions, pgvector HNSW similarity index and project-scoped retrieval and deletion.
- Added offline embedding fixtures and real PostgreSQL vector integration tests. No public RAG endpoints.

- Added a tenth public SEO tool for grounded, editable AI title and description suggestions, with quota and budget gates, evidence validation and local browser tests.

- Added an optional backend-only OpenAI provider adapter, typed generation contracts, streaming, prompt versioning, conservative budgets, token-usage tracking, explicit offline fixtures and privacy controls.
- Documented the LLM layer and kept all public deterministic SEO tools independent of paid AI calls.

- Added heading-outline analysis, bounded same-origin internal link status checks, and Open Graph/X social metadata inspection with an approximate preview.
- Reused secure fetching, Redis quotas, typed reports and shared responsive tool forms.

- Added free redirect-chain, canonical-URL and JSON-LD checkers with source-backed findings and browser tests.

- Added three anonymous, quota-controlled SEO checkers: robots.txt, XML sitemap, and page metadata.
- Connected the web forms to the FastAPI routes through the local same-origin proxy.

- Added deterministic SEO rules, typed evidence-backed findings, normalized URL handling, and fixture tests.
- Extended HTML extraction to retain evidence for repeated titles and canonical declarations.

- Standardized API error responses, server-issued request IDs, and privacy-aware application logging.
- Added Python type and coverage checks, frontend lint/format gates, and automated dependency vulnerability audits.
- Added reproducible dependency-locking and quality documentation.

- Added a responsive website layout, shared interface components, guide pages, planned-tool pages, metadata and browser checks.

- Added database models, Alembic migrations, pgvector setup, a Celery example worker, Docker Compose and infrastructure tests.

- Added an Astro, React, TypeScript, and Tailwind website foundation.
- Added a versioned FastAPI health endpoint with OpenAPI documentation and validated settings.
- Added API and frontend tests, workspace configuration, and foundation checks.
- Added a local development guide and reserved modules for upcoming features.
- Added project documentation, architecture notes, contribution policies, and GitHub templates.

No production application has been released.
