# Account and project security boundaries

The public deterministic SEO checks do **not** require accounts. Private project
metadata requires a password-authenticated session. Private RAG, audit exports,
background jobs and paid AI work **remain disabled in production** at this stage.
A verified project record is necessary but is **not sufficient** to enable deep scans.

## Trust boundaries and threat model

| Component | Untrusted input / threat | Code-level controls | Infrastructure required |
| --- | --- | --- | --- |
| Public check APIs | bots, remote URL attacks, resource exhaustion | Redis peer/host quotas, global bounded fetch slots, short deadlines, content limits, standard-port HTTP(S) | WAF/bot challenges, per-host egress budgets, trusted ingress client IP handling |
| URL fetching and robots | SSRF, redirect pivots, DNS rebinding, cloud metadata | URL normalizer blocks private/loopback/link-local/special IPs; DNS answers must all be public; numerical pinned-IP sockets; TLS verifies the original hostname; same-origin redirects; byte, time and redirect ceilings | Deny RFC1918, link-local, metadata IPs at firewall; private subnet isolation and worker network policy |
| Website verification | invented project/domain control | owner-only unpredictable file challenge stored hashed; HTTPS fetch through pinned transport; exact same host, path, MIME and bytes; no redirect accepted; process-wide verification concurrency limit of two; recheck challenge after fetch | Cloud edge/TLS, anti-abuse throttling, revalidation after domain transfer |
| Accounts and sessions | credential stuffing, session theft, replay, CSRF | scrypt salted passwords, opaque 256-bit tokens hashed in PostgreSQL, 24-hour expiry, server revocation, HttpOnly Secure host-only cookie, SameSite Lax, origin+CSRF token for mutations, Redis login attempt quota | TLS termination, WAF/IP throttling across regions, password-reset and MFA delivery, rate-alerting |
| Project data and RAG | IDOR, cross-project retrieval, prompt injection | per-read project owner predicate; existing RAG query scoping to verified owner; model-generated quotes and references validated | database least privilege, RLS defense-in-depth, private backups/retention |
| Agent and Celery | forged job IDs, retries, poisoned HTML, model tool escalation | private production endpoints disabled; bounded workflow, read-only allowlisted tools and owner rechecks in existing code | separate worker subnet, queue ACLs, job quotas/leases, key separation and egress rules |
| Private HTML/CSV exports | XSS and CSV formula injection | existing escaping and formula-prefix neutralization; private routes absent in production | CSP at edge, HTTPS, sanitized downloads, retention controls |
| Observability | sensitive prompt/log exfiltration | allowlisted telemetry metadata; no raw prompts/page bodies/URLs | trusted OTLP endpoints, scoped collector keys and short retention |
| Cookies/CORS | cross-site writes and credential exfiltration | exact allowlisted frontend origin, credentials only to configured origin; CSRF and origin checks for state changes; no-store on account responses | trusted reverse proxy, correct scheme/host routing, HSTS |
| Public HTML | reflected/embedded malicious data | Astro encoding and HTML sanitization/escaping; deterministic checks treat source as data | strict CSP on pages/CDN, asset integrity and headers |

### Prompt injection

Fetched documents and indexed retrieval content are adversarial. They must never
become system instructions, authentication credentials, tool names, or permission
grants. Current agent tools are read-only and selected from an allowlist; private RAG
is owner-scoped and citations are checked against stored excerpts. **Exact quote
matching is not semantic entailment.** The documented synthetic evaluation includes a
counterexample which current checks incorrectly accept. Before any production paid
agent release, add semantic claim validation, adversarial testing, and human approval
for actions. These mechanisms limit attack impact; they do not prove prompt injection
is impossible.

## Supported account workflow

Production self-registration is disabled intentionally because a verified-email
delivery system, account recovery and MFA have not been integrated. Provision a user
only after independent identity verification using a trusted operator terminal:

```sh
uv run --project apps/api --locked python -m aiseoonline_api.account_admin --email operator@example.org
```

The command prompts without echoing passwords and does not print credentials.
Set the database connection through a protected environment variable. Install
PostgreSQL migration `0006_account_security` before using the routes. For local
integration testing only, set `AISEO_AUTH_REGISTRATION_ENABLED=true` with
`AISEO_ENVIRONMENT=development` or `test` and configure Redis.

1. `POST /api/v1/account/login` with JSON email/password and the exact
   `Origin: https://aiseoonline.com`. The response sets a Secure, HttpOnly,
   SameSite=Lax `__Host-aiseo_session` cookie and returns a CSRF token.
2. `GET /api/v1/account/session` confirms the session and rotates the CSRF
   token. Keep CSRF token in memory only; never log it or put it in URLs.
3. Include `Origin`, `X-CSRF-Token` and cookie on all account-changing
   requests. `POST /api/v1/account/logout` deletes the session row and cookie.
4. `POST /api/v1/account/projects` creates an **unverified** project and
   returns one exact challenge for `/.well-known/aiseoonline-verification.txt`
   at the supplied domain. Place the text on HTTPS with a plain-text response.
5. `POST /api/v1/account/projects/{id}/verify` checks the file through the
   hardened DNS-pinned fetcher. Only exact matches mark the owner's project
   verified; failed attempts do not grant access. Request a new challenge
   with `POST /api/v1/account/projects/{id}/challenge`.
6. `GET /api/v1/account/projects` and `GET /api/v1/account/export` expose
   **only** the authenticated user's project/account metadata. Neither returns
   private indexed body text or audit reports. `DELETE /api/v1/account/projects/{id}`
   deletes projects with no checkpointed audit jobs.

All account endpoints return no-store responses. Existing OpenAPI and API documentation routes remain available for compatibility;\nthese do not grant access to protected project resources. Public SEO utilities remain anonymous, protected by
their existing per-peer and per-domain Redis quotas.

### Data lifecycle and limitations

Account deletion is available with `DELETE /api/v1/account` only if no audit
jobs require separate LangGraph checkpoint cleanup. This is a deliberate
**fail-closed** restriction, not a claim of complete deletion. Other project
data follows database foreign-key cascades. Session rows are revoked by logout
or account deletion and become unusable after 24 hours. Expired rows still
require a scheduled cleanup job. Database backups, telemetry archives, object
storage and LangGraph checkpoint tables require separately designed retention
and purge procedures before accepting sensitive customer data.

There is no verified-email self-service registration, password reset,
multi-factor authentication, self-service user onboarding UI, domain
reverification schedule, or completed data-subject export of private content.
The current export covers account/project metadata only. The project quota
is limited to ten per account, the login rate is capped by Redis peer checks,
and account mutations require CSRF. Shared IPs can hit peer limits;
distributed bots can evade them without edge controls.

### Deferred capabilities

Deep multi-page auditing, public paid AI, production private RAG chat, account
plan entitlements and downloadable private audit reports remain unavailable.
Releasing them requires project-scoped worker authorization at execution time,
budget and concurrency enforcement, cancellation and retention integration,
session-based ownership in all private endpoints, and infrastructure egress
denial. Never enable these routes by bypassing existing production guards.

### Operational deployment requirements

- TLS and exact upstream origins; never trust arbitrary `Forwarded` headers.
- Network-deny metadata endpoints `169.254.169.254`, private CIDRs, IPv6
  local/mapped and all other non-public destinations from crawler **and workers**.
- Redis is required for login, verification and public-request quotas.
  If Redis is unavailable, account writes and paid operations fail closed.
- Protect Redis/PostgreSQL credentials, set database least privilege, rate
  alerting, external backups, data-retention runbooks, and WAF bot challenges.
- Restrict OTLP exporters and secrets; audit production ingress and CSRF/CORS
  headers before accepting users; set domain proof expiration policies.
