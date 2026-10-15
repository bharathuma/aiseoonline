# Security policy

**Support status:** Pre-release codebase. No supported stable V1 or formal
security response-time guarantee is published. Development-only private AI
routes are intentionally excluded from production. Do not treat passing
offline fixtures as a claim of deployed or independently audited security.

## Privately report security vulnerabilities

**Do not post exploit steps, tokens, personal information or private
website contents in a public GitHub issue or PR.**

Use GitHub's **Security → Report a vulnerability** private reporting route
if enabled for this repository. If it is unavailable, request an appropriate
confidential contact method from the maintainer using their
[GitHub profile](https://github.com/bharathumashankar) **without publicly
disclosing vulnerability details**. A dedicated, verified secure contact
channel has not been established and is a production release blocker.

Useful private reports describe the affected component/version, impact,
non-destructive reproduction against systems you own or are permitted to
test, and defensive mitigations. Do not send live credentials or unrelated
user data. There is no guaranteed response SLA.

## Security boundaries

The source implements URL and DNS/IP protections, bounded fetching,
per-peer/host Redis rate limits, hashed password sessions and CSRF checks,
verified-project access, RAG owner scoping and read-only LangGraph tools.
These measures reduce risk; they do not eliminate SSRF or prompt injection.
An offline evaluation preserves a known semantic contradiction falsely
accepted as grounded by the quote checker.

**Not verified for an Internet-facing production rollout:** trusted
Cloudflare proxy client identification, metadata/private-network egress
firewall, distinct database runtime/migration roles, verified-email
onboarding/recovery, full private-content deletion and checkpoint purge,
off-site backup restoration and real operator security monitoring.
Refer to [threat model](docs/security-threat-model.md) and
[release blockers](docs/release-readiness.md).

## Dependency and update process

GitHub Actions run automated Python/frontend vulnerability checks alongside
Ruff, typing, tests and container smoke tests. Automated scanners are
non-exhaustive. Keep dependency locks updated in reviewed PRs, test
migrations and rollback, and never put secrets or production credentials
in source, workflow logs, screenshots or support tickets.

No stable release is implied by repository branches, package version
`0.1.0`, or an accepted PR.
