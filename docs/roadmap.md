# Roadmap

AISEOOnline is in early development. The order below reflects the intended implementation sequence and may change as requirements become clearer.

## Foundation

Set up the Astro frontend, FastAPI backend, shared types and tooling, PostgreSQL, background workers, local containers, and automated checks.

## Public SEO tools

Start with robots.txt and sitemap validators, metadata checks, redirects, canonicals, structured data, headings, internal links, and social metadata. Each tool should provide actionable results and explain its limitations.

## Auditing

Add controlled page crawling, reusable SEO rules, issue grouping, background jobs, and exportable reports. Only permitted sites should be eligible for extensive crawling.

## AI features

Introduce model integrations, structured outputs, retrieval over indexed content, and source-grounded explanations. Use LangGraph for audits that benefit from state, conditional tool use, and recovery.

## Reliability and release

Add evaluations, tracing, quotas, authorization, automated browser tests, deployment procedures, and practical documentation. Release readiness will depend on functioning features and checks, not a fixed deadline.

Issues and releases will record actual progress. A planned feature should not appear as available until it has been implemented and tested.
