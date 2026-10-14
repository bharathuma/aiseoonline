# Development Guide

## Branches and reviews

Use short-lived topic branches from `main`, such as `feat/<name>`, `fix/<name>`, `docs/<name>`, or `chore/<name>`. Pull requests should describe the change, link related issues, and state which checks were run.

Code should be merged after review. Deployments and release tags require separate approval.

## Definition of done

A change is ready for review when:

- It implements the intended behavior without unrelated changes.
- Tests cover meaningful success, failure, and relevant security cases.
- Applicable formatting, linting, type checking, tests, and builds pass.
- Documentation and user-facing claims match actual behavior.
- Public interfaces are accessible and usable across screen sizes.
- Configuration contains no secrets or customer data.
- New dependencies and architectural changes have clear reasons.

If a check was not run, record that limitation.

## Testing

The planned toolchain includes Pytest, Ruff, Python type checking, TypeScript checks, and Playwright. Controlled local fixtures will be used for crawlers and integration tests.

Security tests should cover unsafe URLs, redirects, network timeouts, oversized responses, authorization boundaries, and malicious retrieved content. AI evaluation should use reference datasets and actual observed results. Paid model tests should be opt-in instead of required on each pull request.

Commands and CI workflows will be introduced alongside the application code.

## Releases

Pre-releases may be used while interfaces change. A stable release requires documented installation and rollback procedures, passing checks, reviewed security boundaries, and known limitations.

Merging a pull request does not automatically publish a release or deploy to production.
