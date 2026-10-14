# ADR 0002: FastAPI and a modular monolith

**Status:** Accepted; not implemented.

## Context

The backend needs API endpoints, parsing, database access, background audits, and model integrations. Deploying multiple small network services from the outset would increase operational overhead.

## Decision

Use Python and FastAPI with separate internal modules for crawling, SEO rules, retrieval, and AI. Longer jobs will run in Celery workers.

## Alternatives

Microservices allow independent deployment but bring service discovery, network security, and distributed debugging costs. A serverless-only design may complicate long-running crawl jobs.

## Consequences

The application must keep module boundaries clear. Queue workers will require idempotency, deadlines, cancellation, retries, and observable job state.
