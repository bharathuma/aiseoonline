# Offline SEO evaluations

This repository includes a **synthetic and permission-safe** evaluation dataset at
`apps/api/evaluations/fixtures/seo-v1.json`. Fixtures are fictional example.org
documents, never private site exports. Every case has a stable ID, reference text,
expected tool/factual outcome, and expected citation or rejection.

## Reproduce

After installing the locked API dependencies:

```sh
uv sync --project apps/api --locked --group dev
uv run --project apps/api --locked python -m aiseoonline_api.evaluation --output /tmp/seo-eval.json
uv run --project apps/api --locked pytest apps/api/tests/test_evaluation.py -q
```

To compare *recorded* runs (the same dataset hash and execution mode are required):

```sh
uv run --project apps/api --locked python -m aiseoonline_api.evaluation_history /tmp/baseline.json /tmp/candidate.json
```

Reports record the UTC run time, dataset SHA-256, fixture/provider identity, prompt
template versions, counts, per-case outcomes, and explicit limitations. The comparison
command reports raw paired deltas but never claims statistical significance or model
superiority. GitHub Actions executes the offline CLI and uploads its JSON report, and
ordinary PR checks do **not** call external paid model APIs.

## What each group measures

- **Rank-fusion fixture:** The application’s real reciprocal-rank-fusion implementation
  combines **explicitly supplied, controlled candidate ranks**. Hit@1, recall@3, and
  precision@3 apply only to these supplied rankings. They do **not** measure the
  PostgreSQL hybrid retriever, vector embeddings, live corpus search, or user relevance.
- **RAG safeguards:** The real `verify_draft` method checks expected references, exact
  supporting quotes, numeric claims, and universal claims on fictional excerpts.
  A known semantic-overclaim counterexample is included: an exact quote does not mean
  that a contradictory paraphrase is grounded. The report counts this false acceptance
  as a missed expectation, rather than altering the result.
- **Agent graph:** The actual `AuditAgent` LangGraph executes against injected synthetic
  HTML, a scripted typed provider, and explicit authorization/fetch hooks. Test cases
  check tool invocation, required deterministic findings, partial output on provider
  failure, and refusal to fetch for denied owners. No hosted LLM is evaluated.
- **Metadata generator:** Actual Pydantic `MetaDraft` validation and
  `review_draft` checks are exercised with valid, repeated-title and fabricated-quote
  examples. These measure guard behavior, not generated title quality.

Each score is the number of predefined expectations matched, **not LLM answer accuracy**,
not a comprehensive safety claim and not a search engine performance measurement.
The synthetic dataset is intentionally small. Rank-fusion ranks are hand-supplied,
so excellent recall on this group says little about real retrieval. No model-based
grounding judge or external DeepEval instance runs in automated CI.

## Publication policy

The public `/open-source/benchmarks/` page imports a committed report in
`apps/web/src/data/benchmarks.json`. It displays **no numbers** until a measured report
from a successful CI evaluation is verified and committed. The committed result must
preserve all sample outcomes (including failures), the same fixture hash, and the UTC
date of its real execution. A changed dataset requires a newly measured report.
The page links back to this methodology and the public fixtures.

## Paid/model-based work

Paid nondeterministic evaluations are intentionally **not** in PR workflows. Real model
experiments should run manually in a separately budgeted, credential-controlled
environment against these synthetic documents, record provider usage/pricing and
model/prompt versions, and use multiple runs with uncertainty intervals before any
comparative public claims. DeepEval may be used by such a separate runner when its
API is tested and cost controls are in place; it is **not installed or claimed active**.

No accuracy or quality number should be interpreted as a production KPI without
an appropriately permissioned held-out corpus and independently judged outputs.
