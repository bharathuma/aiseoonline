"""LangGraph SEO audit with bounded model-selected read-only tools.

Authorized one-page evidence only: no public route, multi-page crawl, or write actions.
"""

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from aiseoonline_api.agents.models import (
    AgentDraft,
    AuditFinding,
    AuditReport,
    AuditRequest,
    AuditTrace,
    Recommendation,
    ToolChoice,
)
from aiseoonline_api.agents.tools import build_tools, eligible_tools
from aiseoonline_api.ai_core.contracts import (
    GenerationRequest,
    InvalidModelOutput,
    LLMError,
    LLMProvider,
)
from aiseoonline_api.crawler import CrawlError, CrawlSession, PageSnapshot, normalize_url
from aiseoonline_api.rag.store import RagAccessDenied
from aiseoonline_api.seo_core.models import SeoFinding
from aiseoonline_api.seo_core.rules import analyze_page


class AuditState(TypedDict, total=False):
    request: AuditRequest
    snapshot: PageSnapshot | None
    raw_findings: tuple[SeoFinding, ...]
    findings: tuple[AuditFinding, ...]
    used_tools: tuple[str, ...]
    observations: tuple[dict[str, object], ...]
    next_tool: str | None
    model_calls: int
    trace: tuple[AuditTrace, ...]
    errors: tuple[str, ...]
    recommendations: tuple[Recommendation, ...]
    model: str | None
    token_usage: dict[str, int] | None
    report: AuditReport


def _append(
    state: AuditState, name: str, outcome: str, tool: str | None = None
) -> tuple[AuditTrace, ...]:
    # Never log page bodies, raw prompts, hostnames, or provider error messages.
    return (*state.get("trace", ()), AuditTrace(node=name, outcome=outcome, tool=tool))


def _priority(finding: SeoFinding) -> Literal["high", "medium", "low"]:
    if finding.severity == "error" or finding.rule_id in (
        "robots.noindex",
        "canonical.conflicting",
    ):
        return "high"
    return "medium" if finding.severity == "warning" else "low"


def normalize_findings(items: tuple[SeoFinding, ...]) -> tuple[AuditFinding, ...]:
    normalized: list[AuditFinding] = []
    for finding in items[:40]:
        first = finding.evidence[0]
        ref = first.reference
        key = "|".join(
            (finding.url, finding.rule_id, ref.element, str(ref.ordinal), first.observed)
        )
        fingerprint = hashlib.sha256(key.encode()).hexdigest()[:20]
        normalized.append(
            AuditFinding(
                finding_id=f"seo:{fingerprint}",
                rule_id=finding.rule_id,
                severity=finding.severity,
                priority=_priority(finding),
                affected_url=finding.url,
                summary=finding.summary,
                correction=finding.recommendation,
                evidence_quote=first.observed[:180],
                evidence_ref=f"{ref.element}:{ref.ordinal}",
            )
        )
    weight = {"high": 0, "medium": 1, "low": 2}
    normalized.sort(key=lambda f: (weight[f.priority], f.rule_id, f.finding_id))
    return tuple(normalized)


def verify_recommendations(
    draft: AgentDraft, findings: tuple[AuditFinding, ...]
) -> tuple[Recommendation, ...]:
    indexed = {item.finding_id: item for item in findings}
    recommendations: list[Recommendation] = []
    used: set[str] = set()
    for claim in draft.recommendations:
        finding = indexed.get(claim.finding_id)
        if finding is None or claim.finding_id in used:
            raise InvalidModelOutput("Recommendation cites an unknown or duplicate finding")
        quote = " ".join(claim.supporting_quote.casefold().split())
        observed = " ".join(finding.evidence_quote.casefold().split())
        if quote not in observed:
            raise InvalidModelOutput("Recommendation quote was not in recorded evidence")
        claim_numbers = set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)?%?(?!\w)", claim.advice))
        evidence_numbers = set(
            re.findall(r"(?<!\w)\d+(?:[.,]\d+)?%?(?!\w)", finding.evidence_quote)
        )
        if not claim_numbers.issubset(evidence_numbers):
            raise InvalidModelOutput("Recommendation adds an unsupported numeric claim")
        used.add(claim.finding_id)
        recommendations.append(
            Recommendation(
                finding_id=finding.finding_id,
                affected_url=finding.affected_url,
                priority=finding.priority,
                advice=claim.advice,
                supporting_quote=claim.supporting_quote,
            )
        )
    return tuple(recommendations)


class AuditAgent:
    """Internal service. Caller must supply a real verified-project authorization guard."""

    def __init__(
        self,
        *,
        authorize: Callable[[AuditRequest], None],
        llm: LLMProvider,
        fetch: Callable[[str], PageSnapshot] | None = None,
        rag_lookup: Callable[[AuditRequest, str], list[dict[str, str]]] | None = None,
    ) -> None:
        self.authorize = authorize
        self.llm = llm
        self.fetch = fetch or (lambda url: CrawlSession(url).fetch_page())
        self.rag_lookup = rag_lookup
        graph = StateGraph(AuditState)
        for name, func in (
            ("authorize", self._authorize),
            ("collect", self._collect),
            ("checks", self._checks),
            ("select", self._select),
            ("tool", self._tool),
            ("analyze", self._analyze),
            ("finish", self._finish),
        ):
            graph.add_node(name, func)
        graph.add_edge(START, "authorize")
        graph.add_edge("authorize", "collect")
        graph.add_conditional_edges(
            "collect",
            lambda s: "checks" if s.get("snapshot") else "finish",
            {"checks": "checks", "finish": "finish"},
        )
        graph.add_edge("checks", "select")
        graph.add_conditional_edges(
            "select",
            lambda s: "tool" if s.get("next_tool") else "analyze",
            {"tool": "tool", "analyze": "analyze"},
        )
        graph.add_edge("tool", "select")
        graph.add_edge("analyze", "finish")
        graph.add_edge("finish", END)
        self.graph = graph.compile()

    async def _authorize(self, state: AuditState) -> dict[str, object]:
        req = state["request"]
        normalize_url(req.url)
        self.authorize(req)  # Denials propagate. No network calls before authorization.
        return {"trace": _append(state, "authorize", "verified")}

    async def _collect(self, state: AuditState) -> dict[str, object]:
        req = state["request"]
        try:
            snapshot = await asyncio.to_thread(self.fetch, req.url)
            if (
                normalize_url(snapshot.final_url).origin != normalize_url(req.url).origin
                or snapshot.http_status != 200
            ):
                raise RagAccessDenied("Snapshot outside verified origin or not successful")
            # Recheck owner policy after redirects, before any source content is used.
            self.authorize(req)
            return {"snapshot": snapshot, "trace": _append(state, "collect", "fetched")}
        except CrawlError:
            return {
                "snapshot": None,
                "errors": ("crawler_unavailable",),
                "trace": _append(state, "collect", "partial_failure"),
            }

    async def _checks(self, state: AuditState) -> dict[str, object]:
        snapshot = state["snapshot"]
        assert snapshot is not None
        report = analyze_page(snapshot)
        findings = normalize_findings(report.findings)
        return {
            "raw_findings": report.findings,
            "findings": findings,
            "trace": _append(state, "checks", f"{len(findings)}_findings"),
        }

    async def _select(self, state: AuditState) -> dict[str, object]:
        req = state["request"]
        snapshot = state["snapshot"]
        assert snapshot is not None
        available = [
            name
            for name in eligible_tools(
                snapshot,
                state.get("raw_findings", ()),
                rag_enabled=req.use_private_rag and self.rag_lookup is not None,
            )
            if name not in state.get("used_tools", ())
        ]
        model_calls = state.get("model_calls", 0)
        if (
            not available
            or len(state.get("used_tools", ())) >= req.max_tools
            or model_calls >= req.max_model_calls - 1
            or not state.get("findings")
        ):
            return {"next_tool": None, "trace": _append(state, "select", "budget_or_no_tools")}
        payload = {
            "available_tools": available,
            "finding_codes": [f.rule_id for f in state["findings"][:15]],
            "previous_tools": list(state.get("used_tools", ())),
            "observations": list(state.get("observations", ()))[:3],
        }
        request = GenerationRequest(
            template_id="audit_tool_selection",
            template_version="v1",
            task="Choose one useful available read-only SEO evidence tool, or stop.",
            website_text=json.dumps(payload, ensure_ascii=True)[:3500],
            max_output_tokens=180,
        )
        try:
            answer = await self.llm.complete(request, schema=ToolChoice)
            if not isinstance(answer.value, ToolChoice):
                raise InvalidModelOutput("Tool selection response was not structured")
            picked = answer.value.name
            if picked != "stop" and picked not in available:
                raise InvalidModelOutput("Model requested unauthorized or unavailable tool")
            return {
                "next_tool": None if picked == "stop" else picked,
                "model_calls": model_calls + 1,
                "trace": _append(
                    state,
                    "select",
                    "stopped" if picked == "stop" else "selected",
                    None if picked == "stop" else picked,
                ),
            }
        except (LLMError, ValueError):
            return {
                "next_tool": None,
                "model_calls": model_calls + 1,
                "errors": (*state.get("errors", ()), "tool_planner_unavailable"),
                "trace": _append(state, "select", "partial_failure"),
            }

    async def _tool(self, state: AuditState) -> dict[str, object]:
        snapshot = state["snapshot"]
        assert snapshot is not None
        picked = state.get("next_tool")
        assert picked is not None
        req = state["request"]
        lookup = None
        if picked == "rag" and req.use_private_rag and self.rag_lookup:
            def lookup(query: str) -> list[dict[str, str]]:
                assert self.rag_lookup is not None
                return self.rag_lookup(req, query)
        tools = build_tools(snapshot, state.get("raw_findings", ()), rag_lookup=lookup)
        if picked not in tools:
            raise InvalidModelOutput("Missing approved tool implementation")
        try:
            response = await asyncio.to_thread(tools[picked].invoke, {})
            safe = json.dumps(response, ensure_ascii=True)[:1200]
            return {
                "used_tools": (*state.get("used_tools", ()), picked),
                "observations": (*state.get("observations", ()), {"tool": picked, "result": safe}),
                "next_tool": None,
                "trace": _append(state, "tool", "executed", picked),
            }
        except Exception:
            # Never expose provider details, raw exception text or untrusted HTML to traces.
            return {
                "used_tools": (*state.get("used_tools", ()), picked),
                "errors": (*state.get("errors", ()), "tool_failed"),
                "next_tool": None,
                "trace": _append(state, "tool", "partial_failure", picked),
            }

    async def _analyze(self, state: AuditState) -> dict[str, object]:
        findings = state.get("findings", ())
        calls = state.get("model_calls", 0)
        if not findings or calls >= state["request"].max_model_calls:
            return {"trace": _append(state, "analyze", "no_evidence_or_budget")}
        evidence = [
            {
                "finding_id": f.finding_id,
                "code": f.rule_id,
                "url": f.affected_url,
                "summary": f.summary,
                "evidence": f.evidence_quote,
                "correction": f.correction,
            }
            for f in findings[:10]
        ]
        input_text = json.dumps(
            {"findings": evidence, "tool_observations": state.get("observations", ())},
            ensure_ascii=True,
        )
        if len(input_text) > 11000:
            input_text = json.dumps({"findings": evidence[:6]}, ensure_ascii=True)
        try:
            response = await self.llm.complete(
                GenerationRequest(
                    template_id="audit_recommendations",
                    template_version="v1",
                    task="Suggest six or fewer corrections with verified IDs and exact quotes.",
                    website_text=input_text,
                    max_output_tokens=440,
                ),
                schema=AgentDraft,
            )
            if not isinstance(response.value, AgentDraft):
                raise InvalidModelOutput("Audit response was not structured")
            recommendations = verify_recommendations(response.value, findings)
            return {
                "recommendations": recommendations,
                "model": response.model,
                "model_calls": calls + 1,
                "token_usage": response.usage.model_dump(),
                "trace": _append(state, "analyze", "grounded"),
            }
        except (LLMError, ValidationError, ValueError):
            return {
                "model_calls": calls + 1,
                "errors": (*state.get("errors", ()), "generation_unavailable"),
                "trace": _append(state, "analyze", "partial_failure"),
            }

    async def _finish(self, state: AuditState) -> dict[str, object]:
        snapshot = state.get("snapshot")
        issues = state.get("findings", ())
        errors = state.get("errors", ())
        status = "partial" if errors else "completed"
        if snapshot is None or not issues:
            status = "partial" if errors else "insufficient_evidence"
        report = AuditReport(
            project_id=state["request"].project_id,
            requested_url=state["request"].url,
            final_url=snapshot.final_url if snapshot else None,
            captured_at=snapshot.captured_at if snapshot else None,
            status=status,
            findings=list(issues),
            recommendations=list(state.get("recommendations", ())),
            selected_tools=list(state.get("used_tools", ())),
            trace=list(_append(state, "finish", status)),
            uncertainty=(
                "Some checks or model steps were unavailable; findings remain deterministic."
                if errors
                else "Limited to one permitted HTML snapshot. No browser render or deep scan."
            ),
            model=state.get("model"),
            token_usage=state.get("token_usage"),
        )
        return {"report": report, "trace": tuple(report.trace)}

    async def run(self, request: AuditRequest) -> AuditReport:
        state: AuditState = {
            "request": request,
            "used_tools": (),
            "observations": (),
            "trace": (),
            "errors": (),
            "model_calls": 0,
        }
        # Even infinite/slow provider streams cannot run this graph indefinitely.
        async with asyncio.timeout(request.max_seconds):
            finished = await self.graph.ainvoke(state, config={"recursion_limit": 14})
        return finished["report"]
