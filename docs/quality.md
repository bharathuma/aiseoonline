# Quality checks

The web and API checks run in GitHub Actions on every pull request. Tests that need PostgreSQL or Redis use the isolated infrastructure workflow.

## Python

From the repository root:

```bash
uv sync --project apps/api --locked --group dev
uv run --project apps/api ruff check apps/api
uv run --project apps/api ruff format --check apps/api
uv run --project apps/api mypy apps/api/src
uv run --project apps/api pytest apps/api/tests -q --cov=aiseoonline_api --cov-report=term-missing
```

Type checking covers the application package. Existing integration tests also exercise database migrations, Redis and the worker through GitHub Actions.

## Web

```bash
pnpm install --frozen-lockfile
pnpm lint:web
pnpm format:check:web
pnpm check:web
pnpm test:web
pnpm build:web
pnpm --filter @aiseoonline/web exec playwright install chromium
pnpm e2e:web
```

Formatting uses Prettier with Astro support. ESLint covers TypeScript and JavaScript; Astro's checker covers `.astro` templates. Playwright verifies working navigation, tool search, mobile layouts, dialogs and common accessibility checks.

## Dependency and secrets hygiene

- Commit the generated `apps/api/uv.lock` and `pnpm-lock.yaml`; use locked installs in CI.
- Run `uvx pip-audit` on exported Python runtime requirements and `pnpm audit` for web dependencies. Treat high-severity issues as blockers unless they are documented and reviewed.
- Keep `.env`, secrets, credentials and private content out of the repository. Enable GitHub secret scanning and push protection if available.
- Review third-party actions and keep their permissions minimal. Use reproducible dependency installation rather than passing uncontrolled version ranges into deployment.
- Never run untrusted pull-request changes with write credentials or access to production secrets.

## Branch protection

In GitHub **Settings → Rules → Rulesets**, require a pull request before updating `main`. After this PR's checks stabilize, make the API, web, infrastructure and dependency-audit jobs required. Restrict force pushes and branch deletion. Repository settings must be configured by an administrator; this repository's CI cannot silently enforce them.

Test coverage is reported as a measurement, not an accuracy guarantee. Avoid imposing artificial coverage targets that encourage trivial assertions.

See [API contract](api-contracts.md) for request/response schemas.
