# Release readiness and evidence register

**Status: BLOCKED for production V1.** This is a source and CI assessment, **not** authorization to publish a stable release or to deploy. Review date: 2026-10-15 (UTC). Integrated baseline: `main` at `2fa4250d32514656e53596168dc49ce4bc5dda7a`; CI evidence for this review must also be checked on the final PR commit.

## Recorded isolated CI evidence

The reviewed feature tree passed these checks on October 15, 2026. These
figures are **CI measurements**, not a successful live deployment or external
penetration test:

| Workflow | Actual result | Source |
| --- | --- | --- |
| Foundation | 330 API tests passed, 18 skipped; 78% Python coverage; Ruff, formatting and mypy passed; 55 public Playwright tests and 2 development-browser tests passed | [GitHub Actions run 38755920366](https://github.com/bharathumashankar/aiseoonline/actions/runs/38755920366) |
| PostgreSQL/Redis/Celery | 348 integration-suite tests passed, with additional targeted quota, authorization and retrieval checks | [Run 38755921654](https://github.com/bharathumashankar/aiseoonline/actions/runs/38755921654) |
| Production-mode origin smoke | Isolated Compose startup, migrations, readiness and private route restrictions passed; **no real domain visited** | [Run 38755920150](https://github.com/bharathumashankar/aiseoonline/actions/runs/38755920150) |
| Offline AI evaluations | Synthetic, deterministic evaluation passed with known semantic miss retained | [Run 38755920262](https://github.com/bharathumashankar/aiseoonline/actions/runs/38755920262) |
| Dependency audit | Automated dependency workflow passed | [Run 38755920135](https://github.com/bharathumashankar/aiseoonline/actions/runs/38755920135) |

These runs apply to a pre-squash implementation tree. Check the final PR head's
own fresh workflows before approving a merge. Counts should not be reused for
a different commit without verification.

## Evidence classification

- **Code-inspected:** behavior exists in source and configuration, without implying that hosted infrastructure is installed.
- **Automated regression:** tests run in isolated GitHub Actions services, or with scripted browser/model/network fixtures.
- **Operator not verified:** actual production domain, provider credentials, Cloudflare settings, network policy, legal disclosures, off-host backups and real-user traffic were **not independently tested**.
- **Intentionally disabled:** access is explicitly blocked in production despite development integration coverage.

A passing test suite cannot prove live crawl correctness, general-purpose prompt-injection defense, cloud-security configuration, factual LLM accuracy or accessibility certification.

## Capability-by-capability decision matrix

| Area | Repository evidence | Gate result | Limitation |
| --- | --- | --- | --- |
| Nine no-signup deterministic tools | `public_tools/routes.py`; `test_public_tools.py`; `test_advanced_tools.py`; `test_tool_quality`/Playwright | **Passed in isolated tests** | Browser API replies are fixture scripted; production Redis/routing not independently verified |
| AI metadata drafts | `meta_routes.py`, `test_ai_meta.py`, `test_ai_core.py` | **Passed with scripted model** | Real paid API keys/rates and provider cost/quality untested; no fake fallback |
| Real LangGraph workflow | `agents/workflow.py`, `test_audit_agent.py`, `test_audit_agent_integration.py` | **Passed in dev/test** | Read-only one-page workflow; deliberately absent in production |
| RAG ingestion and hybrid retrieval | `rag/store.py`, `rag/retrieval.py`; retrieval/integration tests | **Passed controlled PostgreSQL fixture** | Embeddings, relevance and factual grounding on live corpora unverified |
| Grounded chat assistant | `rag/assistant.py`, `test_rag_assistant*.py` | **Passed scripted model tests** | Production route disabled; contradictory claim can survive quote-based guard |
| Celery jobs, checkpoint and exports | `agents/execution.py`, `test_audit_jobs_integration.py`, private browser tests | **Passed dev/test integration** | Job controller and private exports not exposed in production |
| Accounts and verification | `accounts.py`, `test_accounts.py`, `test_quality_integration.py` | **Passed test identity and mocked hosted proof** | Production self-signup/recovery/MFA unavailable; no live domain ownership challenge tested |
| Quotas and costs | `public_tools/routes.py`, `meta_routes.py`, `test_public_load.py` | **Passed controlled concurrency/Redis tests** | Shared Cloudflare-proxy IP accounting unresolved; estimates are not provider invoices |
| Observability | `observability.py`, `test_observability.py`, `docs/ai-observability.md` | **Passed local exporter/trace tests** | OTLP/Langfuse disabled without operator endpoints; live retention/collector unverified |
| Offline benchmark | `evaluation.py`, `test_evaluation.py`, published JSON | **17/18 predefined expectations matched** | One known semantic-overclaim false acceptance; zero paid model calls |
| Browser/SEO/accessibility | `technical-seo.spec.ts`, `tool-quality.spec.ts`, `website.spec.ts` | **Passed automated fixture tests** | No real-user performance, manual AT testing or Search Console indexing verification |
| Database, containers, migrations | Infrastructure and production-mode smoke workflows | **Passed disposable Docker/CI services** | No real server deployment, firewall validation, backup restore drill or external availability test |
| External live `aiseoonline.com` | No verified production-run result as part of this review | **Not verified** | Do not claim the domain serves this source revision |

### Benchmark integrity

The committed synthetic benchmark is **18 cases** grouped as 4 supplied-rank RRF exercises, 7 RAG checks, 4 LangGraph checks and 3 metadata validation checks. **17 match expected behavior**, and `rag-semantic-overclaim` is an **unfixed false acceptance**. It is not an 94%-accurate AI model; the matched proportion measures fixture expectations only. The dataset hash and per-case results are regression-tested against the offline evaluator. No claims of retriever relevance, model superiority, live-crawl success or search-engine indexing are justified.

## Release-blocking gaps

| ID | Severity | Blocker | Required evidence to close |
| --- | --- | --- | --- |
| REL-001 | **Blocking: production private AI** | All LangGraph audit job and RAG-chat API routes are intentionally excluded from `production`; owners cannot access those features there. | Implement session-derived authorization, ownership, verified-site checks, bounded worker entitlements, end-to-end paid cost gates, report/checkpoint retention, and production-mode integration tests before promising private AI |
| REL-002 | **Blocking: production security** | Outbound cloud metadata/private-address firewall policies, trusted Cloudflare client-IP attribution, runtime-vs-migration DB roles and real WAF limits have not been configured/verified. | Operator-verified host egress deny, trusted proxy validation and quota tests, least-privilege migrations/app DB user, monitored WAF policies |
| REL-003 | **Blocking: collecting private user data** | Self-service verified-email onboarding, account recovery, confidential support contact, complete private export and checkpoint/backup erasure are not implemented. | Demonstrated deletion/retention lifecycle, verified private contact, operator/legal privacy review, hardened account operations |
| REL-004 | **Blocking: production release validation** | No credentials or permission to inspect/run the actual VPS/Cloudflare/CDN, TLS configuration, off-site backups, external monitoring, or domain serving this revision. | Approved isolated staging release, external TLS/CDN/API/whois/robots/sitemap/header checks, restore drill, alert exercises, and operator signoff |
| REL-005 | **Blocking: advertising/analytics activation** | Opt-in consent, analytics and ad slots are intentionally disabled, and operator privacy/legal policies remain drafts. | Separate explicit approval, consent/legal review and measured page layout/traffic verification before enabling any tracking or ad code |

`REL-005` does **not block running the site without ads or analytics**; it blocks claiming monetization readiness. `REL-001` does **not block standalone deterministic tools** but blocks describing the whole AI audit suite as a production V1. **Do not mark a comprehensive production V1 ready while REL-001 through REL-004 remain open.**

## Nonblocking but important improvements

- **N-001:** Humans must check screen readers, focus order, contrast and low-end/mobile physical devices; automated axe does not certify WCAG.
- **N-002:** Measure real user p75 Core Web Vitals and production CDN/cache/DB query behavior; previous p50/p95 API numbers are from mocked 25 ms fetches, not real Internet load.
- **N-003:** Add larger permission-cleared, independent held-out retrieval/model evaluation (including contradiction detection, corpus drift and costs) before public quality comparisons.
- **N-004:** Verify the final legal operator identity, secure contact and Terms/Privacy draft; do not represent source placeholders as finalized legal documents.
- **N-005:** Configure actual secret rotation, off-site PITR backups, alert thresholds and on-call incident runbooks.
- **N-006:** Collect genuine screenshots/video locally or from approved staging; no synthetic screenshots are included.

## Release decision and scope

**Decision: NO-GO for comprehensive production V1.** The repository is a meaningful open-source **pre-release portfolio and runnable local application** with automated integration evidence. Public deterministic tools may be considered for a **separately authorized, security-reviewed limited release** after infrastructure and legal validation. Production private AI/deep scans cannot be unlocked by relabeling deployment flags; code, end-to-end tests, and operator approval are prerequisites.

Recheck all current workflow results on the PR head. CI test totals and recorded build measurements change over time; always quote the latest run IDs and note skipped tests. See [release action checklist](release-checklist.md), [deployment](deployment.md), [quality review](quality-review.md), [security threat model](security-threat-model.md), and [benchmark methodology](evaluations.md).

**Never publish a stable V1 tag, merge a release PR or deploy without explicit separate operator approval.**
