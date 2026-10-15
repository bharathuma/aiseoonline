# Operator-owned release and deployment checklist

This is a **future action list**, not a permission to tag, publish images,
enable model billing, make DNS changes, deploy, or announce a stable version.
Current decision: [BLOCKED](release-readiness.md). Preserve the repository's
pre-release state until every *applicable* blocking condition is resolved and
explicit approval is recorded separately.

## Code and quality gates

- [ ] Resolve `REL-001` to `REL-004` for a **comprehensive** production V1;
      alternatively obtain explicit approval for a narrowly scoped
      deterministic-tools-only release without suggesting private AI is public.
- [ ] Confirm current `main` is integrated, protected, reviewed and stable.
- [ ] Run *all* GitHub Actions: API lint/format/mypy/pytest; static build,
      type check, UI and Playwright; PostgreSQL/Redis/Celery migrations,
      checkpoint recovery, real Compose boot, deployment smoke, dependency
      audits, offline evaluator and release-contract checks.
- [ ] Inspect **job-level logs**, skipped tests, actual fixture hashes and
      incomplete/error cases. A green summary without source inspection is
      insufficient.
- [ ] Run `docker compose up --build -d` from a fresh checkout with a fresh
      `.env`, then the documented readiness, Celery ping, migrations and
      report checks. Repeat in an **isolated approved staging** environment.
- [ ] Verify ten real public tool forms against **permitted** public test
      domains; confirm actual data in downloaded reports, not only mocked
      browser responses.
- [ ] Verify explicit no-key/model-provider errors and budget exhaustion; do
      not activate paid API access by accident.
- [ ] Reproduce recorded offline benchmark and preserve known failures rather
      than replacing them with fabricated successes.
- [ ] Review keyboard/mobile/screen-reader behavior manually and check
      actual external p75 Core Web Vitals where measurement is available.

## Infrastructure, privacy and recovery gates

- [ ] Verify host egress firewall denies private/CIDR/cloud metadata access,
      including from worker containers; simulate DNS rebinding and redirects.
- [ ] Verify Cloudflare TLS/DNS, proxy trust, client-IP source and visitor
      quotas, bot/WAF rules, caching and HSTS. Never trust arbitrary forwarded
      identity.
- [ ] Create separate least-privileged DB runtime and migration identities.
- [ ] Confirm operator contact, legal jurisdiction, retention/backup deletion,
      account recovery and secure vulnerability reporting.
- [ ] Rotate/restrict model, database, Redis, GitHub and tunnel credentials.
      Run secrets scanning and confirm no production secrets in build files.
- [ ] Configure PITR/encrypted off-site backups, **perform a clean restore
      drill**, and demonstrate safe rollback across schema versions.
- [ ] Exercise alerting for Redis/PostgreSQL outages, queue growth, failing
      readiness, token budget exhaustion and CDN/origin downtime.
- [ ] Confirm private jobs, reports and RAG cannot be reached by strangers;
      verify owner separation and noindex are not mistaken for authorization.
- [ ] Complete genuine screenshots/demo recording and independent operator
      signoff on displayed statistics and legal text.

## Only after all required checks pass and explicit approval is given

1. Choose a verified release scope and version; prepare sanitized release
   notes with tested commit SHA, date, known issues, and supported operation
   modes.
2. Ask for **separate explicit permission** to create a stable GitHub V1 tag
   or GitHub Release. Do not infer release approval from a PR merge.
3. Use the manually gated GHCR workflow to build and publish digest-pinned
   images only after protected GitHub Environment approval.
4. Ask for **separate explicit permission** to deploy to staging or production.
   Review target host, hostname, Cloudflare tunnel, secrets, backups and
   rollback strategy before any changes.
5. Smoke-test public requests/headers, real ownership, quotas, report privacy,
   opt-in observability and backup restore **after** deployment. Record
   evidence and rollback on regressions.
6. Publish a dated release announcement only when the publicly reachable
   site and declared release capabilities have been independently verified.

**No stable tag, Release object or production deployment has been created by this checklist.**
