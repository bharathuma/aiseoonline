# Genuine screenshot capture and 3–5-minute demo walkthrough

**Use real application output, not fabricated screenshots, model replies or traffic.**
This demo can be recorded using the isolated local Docker Compose installation.
It does not require paid API credentials or a live domain.

## Capture environment

1. Clone the current reviewed commit; copy `.env.example` to a private `.env` and generate fresh DB/Redis passwords.
2. Run `docker compose up --build -d`; verify `/api/v1/ready` from `http://127.0.0.1:4321`, inspect `docker compose ps`, and keep the terminal readable.
3. Set browser width to 1440px for desktop and 390px for mobile; record the address bar showing `127.0.0.1`. Use your **own** public test URL or a controlled local/mock fixture URL the backend is permitted to reach. Do not screen-record any real account token, password, secret, customer crawl, or private text.
4. Capture the homepage, tool directory, meta checker before submit, **real resulting** evidence and report download, mobile navigation, benchmark limitations, and workflow graph via a Markdown renderer (or local source viewer).
5. Place files in an untracked local recording folder; never commit screenshots exposing test identity or private content. If you publish sanitized screenshots later, describe them as `local test` or `staging` with date and tested revision. UI-only screenshots require no fabricated report values.
6. Confirm browser is not serving stale assets from a prior build. With no paid provider configured, **show the generator's explicit unavailable response** instead of simulating a successful paid call.

## Spoken script (roughly 4 minutes at conversational pace)

**0:00–0:30 — Who this serves.**

> AISEOOnline is an open-source SEO toolkit with independently useful single-purpose tools. Rather than giving every site a mysterious optimization score, its checks show the observed evidence and tell you what remains uncertain. The source is public, and this demo uses a local test environment—not a production traffic claim.

**0:30–1:10 — Public workflow.**

> Here is the tool directory. I can inspect robots files, XML sitemaps, metadata, redirect hops, canonical hints, JSON-LD, headings, internal links and social sharing fields without creating an account. Each page has practical instructions, a bounded check, example findings and limitations. I'll enter an allowed test URL into the meta checker and run it. Notice that the response shows the source URL, the facts that were observed, and any specific corrective recommendations. This report downloads as JSON so the results can be examined or compared. There are no guaranteed ranking predictions.

**1:10–1:55 — Architecture.**

> The interface is mostly statically rendered Astro, with React forms only where needed. Those forms call FastAPI through a same-origin proxy. The server validates URLs, checks shared Redis limits, resolves DNS safely, verifies public IP destinations and restricts redirects, response sizes, time and concurrency. Deterministic rules derive technical findings from downloaded evidence. PostgreSQL owns project identity and records, and Celery manages longer-running development workflows.

**1:55–2:45 — Agents and retrieval.**

> The private audit implementation is a real LangGraph state machine, not a hard-coded output. It first authorizes a verified project, fetches one permitted page, creates deterministic findings, and optionally lets a model choose from a small list of read-only LangChain tools. A conditional loop bounds those selections and costs. It can retrieve project-scoped content from PostgreSQL using keyword and vector candidates with rank fusion. Generated explanations must cite recorded evidence, but quote matching is not the same as proving semantic truth. These workflows are tested in development and are intentionally not exposed on the production API.

**2:45–3:30 — Honest evaluation.**

> Here are the offline benchmark fixtures and documented methodology. The tests exercise actual rank fusion against supplied candidate lists, actual graph transitions with a scripted provider, evidence guardrails, and structured output checks. In the current 18-case synthetic suite, 17 expectations match and one semantic contradiction is missed. I show that miss because the evaluation must surface blind spots, not hide them. No model accuracy or live retrieval quality is inferred from these fixture outcomes.

**3:30–4:10 — Reliability, safeguards and tradeoffs.**

> Integration tests exercise real PostgreSQL, Redis, migrations, Celery jobs, checkpoint recovery and authorization boundaries. Browser tests cover mobile layouts, navigation, every public checker, and failures. Model calls are optional and cost-gated. Tracing can export allowlisted metadata to an operator-configured OTLP or Langfuse endpoint without publishing raw prompts or crawl text. The private origin has a reproducible Docker deployment configuration, but production firewall, legal, account and data-retention work remains open.

**4:10–4:35 — Close.**

> This project shows how I separate deterministic evidence from probabilistic suggestions, build an agent with controlled tools, and test security and failure paths. It's a useful local and open-source system; I am not presenting the still-disabled private workflows or this GitHub revision as a launched production SaaS. The README and release audit link to actual tests, known limitations, and next engineering decisions.

## Capture checklist

- [ ] Capture only the real current revision and clearly mark local/staging context.
- [ ] Show a successful result **only after** the actual backend responds successfully.
- [ ] Show at least one explicit error state and a mobile viewport.
- [ ] Show the RAG/evaluation failure disclosure and that private AI endpoints are disabled in production.
- [ ] Blur/no-show any credentials, real account IDs, auth cookies, secret environment files, or third-party content without permission.
- [ ] Link source commit and CI run; check any statistics against real logs.
- [ ] Keep the final video unlisted/private until reviewed and explicitly approved for publication.
