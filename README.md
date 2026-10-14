# AISEOOnline

Open-source SEO tools for checking, understanding, and improving websites.

**Status: Under development.** The application is not available from this repository yet.

AISEOOnline is intended to make routine SEO checks easier for site owners, developers, and teams. It will offer free single-purpose utilities alongside site-wide auditing and AI-assisted analysis.

## Planned features

**SEO tools**
- Validate robots.txt files and XML sitemaps.
- Inspect titles, descriptions, headings, canonicals, redirects, and structured data.
- Check internal links and social sharing metadata.
- Generate alternative meta titles and descriptions.

**Site auditing**
- Scan permitted pages within configurable limits.
- Group technical findings by page and severity.
- Provide reports with source URLs and actionable explanations.

**AI-assisted analysis**
- Explain verified findings and suggest priorities.
- Answer questions about indexed site content with source references.
- Coordinate supported auditing tools in bounded workflows.

Technical checks will be implemented with repeatable rules; model-generated suggestions will not replace factual checks or guarantee search rankings.

## Technology

The proposed stack includes Astro, React, TypeScript, Tailwind CSS, Python, FastAPI, Pydantic, PostgreSQL, pgvector, Redis, Celery, LangChain, and LangGraph. AI integrations, evaluation, and tracing will be added as those features are implemented.

The initial architecture is described in [docs/architecture.md](docs/architecture.md), with design rationale in the [decision records](docs/adr/README.md).

## Roadmap

- Application and API foundations.
- Free SEO checking tools.
- Site auditing and background processing.
- AI analysis and retrieval.
- Evaluation, monitoring, and deployment.

The [roadmap](docs/roadmap.md) has additional detail. Roadmap items are proposed, not shipped. There is no local setup command until application code is introduced.

## Contributing

Contributions, bug reports, and feature ideas are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow the [security reporting policy](SECURITY.md).

## License

Licensed under the [Apache License 2.0](LICENSE).

Website: [aiseoonline.com](https://aiseoonline.com)
