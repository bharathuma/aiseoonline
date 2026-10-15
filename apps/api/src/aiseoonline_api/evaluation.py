"""Offline, permission-safe evaluations of existing SEO safeguards and graph behavior.

No provider network requests, database access, production content, or live embeddings.
The retrieval exercise replays *supplied rankings* through the real RRF function;
it must never be described as a measured hybrid search or model retrieval score.
"""

import argparse
import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError

from aiseoonline_api.agents.models import AgentClaim, AgentDraft, AuditRequest, ToolChoice, ToolName
from aiseoonline_api.agents.workflow import AuditAgent
from aiseoonline_api.ai_core.contracts import (
    GenerationRequest,
    InvalidModelOutput,
    ModelResult,
    ProviderUnavailable,
    StreamEvent,
    TokenUsage,
)
from aiseoonline_api.ai_core.meta_generator import MetaDraft, review_draft
from aiseoonline_api.crawler import PageSnapshot, parse_html
from aiseoonline_api.rag.assistant import (
    AnswerDraft,
    EvidenceSource,
    GroundedClaim,
    verify_draft,
)
from aiseoonline_api.rag.retrieval import reciprocal_rank_fusion
from aiseoonline_api.rag.store import RagAccessDenied

DATASET = Path(__file__).resolve().parents[2] / "evaluations/fixtures/seo-v1.json"
FIXED_TIME = datetime(2026, 10, 15, tzinfo=UTC)
PROJECT = UUID("11111111-1111-4111-8111-111111111111")
OWNER = UUID("22222222-2222-4222-8222-222222222222")
SITE = "https://example.org/audit"
MODEL = "deterministic-scripted-provider"
PROMPT_VERSIONS = {"audit_tool_selection": "v1", "audit_recommendations": "v1", "meta_draft": "v1"}


def load_dataset(path: Path = DATASET) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    dataset = json.loads(raw)
    if dataset["version"] != "seo-evaluation-v1":
        raise ValueError("Unsupported evaluation dataset version")
    if not dataset["documents"] or not dataset["rag"] or not dataset["agent"]:
        raise ValueError("Evaluation dataset is incomplete")
    identifiers = [doc["id"] for doc in dataset["documents"]]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate document identifiers")
    known = set(identifiers)
    all_cases: list[str] = []
    for group in ("retrieval", "rag", "agent", "structured"):
        for case in dataset[group]:
            all_cases.append(case["id"])
            if (
                group == "retrieval"
                and not set(case["semantic_ids"] + case["keyword_ids"] + case["expected_ids"])
                <= known
            ):
                raise ValueError("Ranking references a missing synthetic document")
            if group == "rag" and case["source_id"] != "made-up" and case["source_id"] not in known:
                raise ValueError("RAG case references an unknown synthetic document")
    if len(all_cases) != len(set(all_cases)):
        raise ValueError("Duplicate evaluation case identifiers")
    return dataset, hashlib.sha256(raw).hexdigest()


def _case(category: str, case_id: str, passed: bool, *, detail: str) -> dict[str, object]:
    return {"category": category, "id": case_id, "matched_expectation": passed, "detail": detail}


def evaluate_rankings(data: dict[str, Any]) -> list[dict[str, object]]:
    """Measures supplied-channel RRF only; not actual retrieval/search performance."""
    ids = {doc["id"]: UUID(int=i + 1) for i, doc in enumerate(data["documents"])}
    reverse = {value: key for key, value in ids.items()}
    rows: list[dict[str, object]] = []
    for case in data["retrieval"]:
        scores = reciprocal_rank_fusion(
            [ids[k] for k in case["semantic_ids"]],
            [ids[k] for k in case["keyword_ids"]],
        )
        ordered = [reverse[k] for k in sorted(scores, key=lambda k: (-scores[k], str(k)))]
        target = set(case["expected_ids"])
        top = ordered[:3]
        relevant = len(target.intersection(top))
        rows.append(
            {
                **_case(
                    "rrf_fixture", case["id"], relevant > 0, detail="supplied_candidate_rankings"
                ),
                "precision_at_3": round(relevant / max(1, len(top)), 6),
                "recall_at_3": round(relevant / len(target), 6),
                "hit_at_1": ordered[0] in target,
            }
        )
    return rows


def evaluate_rag(data: dict[str, Any]) -> list[dict[str, object]]:
    sources = {
        doc["id"]: EvidenceSource(
            source_id="rag:" + doc["id"],
            kind="indexed_page",
            source_url=doc["url"],
            captured_at=FIXED_TIME,
            excerpt=doc["text"],
        )
        for doc in data["documents"]
    }
    rows: list[dict[str, object]] = []
    for case in data["rag"]:
        chosen = case["source_id"]
        source_id = "rag:" + chosen if chosen in sources else "rag:invented"
        accepted = False
        try:
            draft = AnswerDraft(
                claims=[
                    GroundedClaim(
                        statement=case["statement"],
                        source_id=source_id,
                        supporting_quote=case["quote"],
                    )
                ]
            )
            result = verify_draft(
                PROJECT,
                draft,
                list(sources.values()),
                model=MODEL,
                usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )
            accepted = bool(result.statements)
        except (InvalidModelOutput, ValidationError):
            pass
        predicted = "accepted" if accepted else "rejected"
        rows.append(
            {
                **_case(
                    "rag_guard",
                    case["id"],
                    predicted == case["expected"],
                    detail=str(case["expected_fact"]),
                ),
                "observed": predicted,
                "expected": case["expected"],
                "valid_citation": (
                    chosen in sources
                    and case["quote"].casefold() in sources[chosen].excerpt.casefold()
                ),
            }
        )
    return rows


class _ScriptedAgentProvider:
    """Deterministic scripted decisions, routed into the real authorized LangGraph."""

    def __init__(self, tool: str | None, *, unavailable: bool = False) -> None:
        self.tool = tool
        self.unavailable = unavailable
        self.calls = 0

    async def complete(self, request: Any, *, schema: Any = None) -> ModelResult[Any]:
        self.calls += 1
        if self.unavailable:
            raise ProviderUnavailable("Synthetic provider outage")
        if schema is ToolChoice:
            value: Any = ToolChoice(
                name=cast(ToolName, self.tool or "stop"), reason="Inspect actual captured evidence"
            )
        elif schema is AgentDraft:
            findings = json.loads(request.website_text)["findings"]
            recommendation = []
            if findings and len(findings[0]["evidence"]) >= 3:
                recommendation.append(
                    AgentClaim(
                        finding_id=findings[0]["finding_id"],
                        supporting_quote=findings[0]["evidence"][:90],
                        advice="Review this detected SEO issue before making changes.",
                    )
                )
            value = AgentDraft(
                recommendations=recommendation, uncertainty="Only the synthetic page was inspected."
            )
        else:
            raise AssertionError("Unexpected agent output schema")
        return ModelResult(
            value=value,
            model=MODEL,
            usage=TokenUsage(input_tokens=70, output_tokens=30, total_tokens=100),
            cost_usd=Decimal(0),
            prompt_id=request.template_id,
            prompt_version=request.template_version,
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        raise AssertionError("Streaming is not part of scripted evaluations")
        if False:
            yield StreamEvent(kind="done")


async def _agent_case(case: dict[str, Any]) -> dict[str, object]:
    calls = {"fetched": 0}
    provider = _ScriptedAgentProvider(
        case["tool"], unavailable=case["mode"] == "provider_unavailable"
    )

    def authorize(_request: AuditRequest) -> None:
        if case["mode"] == "access_denied":
            raise RagAccessDenied("Synthetic project access denied")

    def fetch(_url: str) -> PageSnapshot:
        calls["fetched"] += 1
        html = case["html"]
        return PageSnapshot(
            requested_url=SITE,
            final_url=SITE,
            captured_at=FIXED_TIME,
            http_status=200,
            redirects=(),
            content_bytes=len(html.encode()),
            html=parse_html(html.encode(), SITE),
        )

    agent = AuditAgent(authorize=authorize, llm=provider, fetch=fetch)
    request = AuditRequest(
        project_id=PROJECT,
        owner_id=OWNER,
        url=SITE,
        max_tools=1,
        max_model_calls=2,
        max_seconds=15,
    )
    if case["mode"] == "access_denied":
        try:
            await agent.run(request)
            blocked = False
        except RagAccessDenied:
            blocked = True
        passed = blocked and calls["fetched"] == 0 and provider.calls == 0
        return {
            **_case("agent_graph", case["id"], passed, detail="authorization_before_fetch"),
            "status": "denied" if blocked else "unexpected_access",
            "tool_count": 0,
        }
    result = await agent.run(request)
    selected = result.selected_tools
    facts = {finding.rule_id for finding in result.findings}
    passed = (
        result.status == case["expected_status"]
        and (case["tool"] is None or case["tool"] in selected)
        and (case["tool"] is not None or not selected)
        and case["expected_finding"] in facts
        and all(
            rec.requires_human_approval and not rec.action_executed
            for rec in result.recommendations
        )
        and calls["fetched"] == 1
    )
    return {
        **_case("agent_graph", case["id"], passed, detail="actual_langgraph_execution"),
        "status": result.status,
        "tool_count": len(selected),
        "finding_count": len(result.findings),
    }


def evaluate_agent(data: dict[str, Any]) -> list[dict[str, object]]:
    return asyncio.run(_evaluate_agent(data))


async def _evaluate_agent(data: dict[str, Any]) -> list[dict[str, object]]:
    return [await _agent_case(case) for case in data["agent"]]


def evaluate_structured(data: dict[str, Any]) -> list[dict[str, object]]:
    source = data["documents"][0]["text"]
    basic = [
        {
            "title": title,
            "description": description,
            "evidence_quote": "A robots.txt Disallow directive requests",
            "rationale": "Based on the referenced crawler instruction.",
        }
        for title, description in (
            (
                "Understanding robots.txt crawler restrictions",
                "Find out what the Disallow directive tells compatible website crawlers to do.",
            ),
            (
                "Disallow directives and safe website access",
                "Learn why crawler rules are different from authorization and private access.",
            ),
            (
                "Robots access rules explained for site owners",
                "Explore crawler requests and why these files cannot hide sensitive information.",
            ),
        )
    ]
    rows: list[dict[str, object]] = []
    for case in data["structured"]:
        examples = [dict(x) for x in basic]
        if case["kind"] == "duplicate_title":
            examples[1]["title"] = examples[0]["title"]
        if case["kind"] == "invented_quote":
            examples[0]["evidence_quote"] = "A guarantee of number one Google rankings"
        accepted = False
        try:
            draft = MetaDraft.model_validate({"suggestions": examples})
            accepted = len(review_draft(draft, source)) == 3
        except (InvalidModelOutput, ValidationError):
            pass
        predicted = "accepted" if accepted else "rejected"
        rows.append(
            {
                **_case(
                    "structured_meta",
                    case["id"],
                    predicted == case["expected"],
                    detail="actual_schema_and_evidence_review",
                ),
                "observed": predicted,
            }
        )
    return rows


def benchmark(dataset: dict[str, Any], dataset_hash: str, *, run_at: str) -> dict[str, Any]:
    samples = (
        evaluate_rankings(dataset)
        + evaluate_rag(dataset)
        + evaluate_agent(dataset)
        + evaluate_structured(dataset)
    )
    groups: dict[str, dict[str, object]] = {}
    for key in ("rrf_fixture", "rag_guard", "agent_graph", "structured_meta"):
        cases = [item for item in samples if item["category"] == key]
        passed = sum(bool(item["matched_expectation"]) for item in cases)
        groups[key] = {
            "cases": len(cases),
            "matched": passed,
            "match_rate": round(passed / len(cases), 6) if cases else None,
        }
    rrf = [item for item in samples if item["category"] == "rrf_fixture"]
    groups["rrf_fixture"]["mean_recall_at_3"] = round(
        sum(cast(float, x["recall_at_3"]) for x in rrf) / len(rrf), 6
    )
    groups["rrf_fixture"]["hit_at_1"] = sum(bool(x["hit_at_1"]) for x in rrf)
    return {
        "schema_version": 1,
        "dataset_version": dataset["version"],
        "dataset_sha256": dataset_hash,
        "run_at_utc": run_at,
        "mode": "offline_scripted_fixture",
        "model": MODEL,
        "prompt_versions": PROMPT_VERSIONS,
        "data_policy": "synthetic_only",
        "paid_calls": 0,
        "measurement_scope": (
            "Real citation verifier, audit graph, metadata validator and RRF fusion "
            "using synthetic inputs and scripted decisions; not live-model or DB retrieval quality"
        ),
        "case_count": len(samples),
        "groups": groups,
        "cases": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run offline SEO regression evaluations")
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data, digest = load_dataset(args.dataset)
    measured_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    report = benchmark(data, digest, run_at=measured_at)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    for name, stats in report["groups"].items():
        print(f"{name}: {stats['matched']}/{stats['cases']} expectations matched")
    print(f"dataset_sha256={digest}")
    print(f"report_file={args.output}")


if __name__ == "__main__":
    main()
