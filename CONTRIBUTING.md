# Contributing

AISEOOnline welcomes small, useful public-tool fixes, accurate documentation,
accessibility improvements and evidence-backed test coverage. The source is
pre-release; please avoid describing development-only private AI features
as production functionality.

## Reproduce the current application

Follow [local setup](docs/getting-started.md) to configure independent private
database/Redis passwords and start the Docker Compose stack. Node.js 22.12+,
pnpm 10, Python 3.12+ and uv are needed for host-based development.

```bash
corepack enable
pnpm install --frozen-lockfile
uv sync --project apps/api --locked --group dev
uv run --project apps/api --locked ruff check apps/api
uv run --project apps/api --locked ruff format --check apps/api
uv run --project apps/api --locked mypy --config-file apps/api/pyproject.toml apps/api/src
uv run --project apps/api --locked pytest apps/api/tests -q
pnpm lint:web && pnpm format:check:web && pnpm test:web
pnpm check:web && pnpm build:web
pnpm --filter @aiseoonline/web exec playwright install chromium
pnpm e2e:web
```

Integration tests needing PostgreSQL, Redis and Celery are run in isolated
GitHub Actions; test skips in a host-only run are **not** evidence those
integration paths passed locally.

## Make changes

1. Search existing issues before proposing a new checker or architecture.
   For major changes, open a focused issue with acceptance criteria first.
2. Branch from current `main`; avoid unrelated refactors.
3. Keep deterministic checks separate from optional AI suggestions and
   preserve actual input evidence. Explicitly handle untrusted HTML,
   authentication, network failures, cost caps and resource ceilings.
4. Use permission-safe synthetic fixtures and add normal, edge, failure,
   authorization and browser tests as needed. Never commit private crawl
   material, real API keys, screenshots containing user data or paid calls.
5. Update user docs and security notes when behavior changes.
6. Open a PR with what actually changed, tests **actually run** and known
   limitations. Green PR checks do not authorize a merge or deployment.

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
Follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Contributions to this
repository are published under [Apache License 2.0](LICENSE).

Further information: [architecture](docs/architecture.md),
[quality](docs/quality.md), [evaluation](docs/evaluations.md) and
[release-readiness gates](docs/release-readiness.md).
