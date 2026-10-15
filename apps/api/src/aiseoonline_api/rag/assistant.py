"""Private, evidence-grounded RAG question answering with verified citations.

The caller authenticates before instantiating this service. No web crawling, database
writes, conversation persistence or model side-effects are performed here.
"""

import json
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiseoonline_api.ai_core.contracts import GenerationRequest, InvalidModelOutput, LLMProvider
from aiseoonline_api.crawler import normalize_url
from aiseoonline_api.crawler.urls import UnsafeTarget
from aiseoonline_api.db.models import AuditJob, Page, Project, SeoFinding
from aiseoonline_api.rag.retrieval import HybridRetriever, RetrievalOptions
from aiseoonline_api.rag.store import RagAccessDenied


class QuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: UUID
    question: str = Field(min_length=8, max_length=500)
    previous_questions: list[str] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def check_history(self) -> "QuestionInput":
        if any(not 5 <= len(turn.strip()) <= 400 for turn in self.previous_questions):
            raise ValueError("Previous questions must be 5–400 characters each")
        return self


class GroundedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=12, max_length=350)
    source_id: str = Field(min_length=8, max_length=160)
    supporting_quote: str = Field(min_length=8, max_length=300)


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[GroundedClaim] = Field(max_length=4)
    uncertainty: str = Field(default="", max_length=250)


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    kind: Literal["indexed_page", "seo_finding"]
    source_url: str
    document_id: UUID | None = None
    chunk_id: UUID | None = None
    finding_id: UUID | None = None
    section_heading: str | None = None
    captured_at: datetime
    excerpt: str = Field(min_length=8, max_length=1100)


class AnswerStatement(BaseModel):
    statement: str
    source_id: str
    supporting_quote: str


class GroundedAnswer(BaseModel):
    project_id: UUID
    statements: list[AnswerStatement]
    sources: list[EvidenceSource]
    uncertainty: str
    model: str | None = None
    token_usage: dict[str, int] | None = None
    evidence_scope: str = (
        "Limited to indexed excerpts and recorded findings for this verified project. "
        "This is not a complete website audit."
    )


def check_project(session: Session, project_id: UUID, owner_id: UUID) -> None:
    allowed = session.scalar(
        select(Project.id).where(
            Project.id == project_id,
            Project.owner_id == owner_id,
            Project.verification_status == "verified",
        )
    )
    if allowed is None:
        raise RagAccessDenied("Verified ownership required")


def _clean(text: str) -> str:
    return " ".join(text.casefold().split())


def _findings(
    session: Session,
    project_id: UUID,
    question: str,
    *,
    max_items: int = 8,
) -> list[EvidenceSource]:
    """Use only recorded findings attached to a completed audit and scoped page."""
    audit_id = session.scalar(
        select(AuditJob.id)
        .where(AuditJob.project_id == project_id, AuditJob.status == "completed")
        .order_by(AuditJob.created_at.desc(), AuditJob.id.desc())
        .limit(1)
    )
    if audit_id is None:
        return []
    project_domain = session.scalar(select(Project.domain).where(Project.id == project_id))
    records = list(session.execute(
        select(SeoFinding, Page)
        .join(Page, SeoFinding.page_id == Page.id)
        .where(
            SeoFinding.audit_job_id == audit_id,
            Page.audit_job_id == audit_id,
            Page.project_id == project_id,
        )
        .order_by(SeoFinding.id)
        .limit(120)
    ).all())
    question_text = _clean(question)
    if "description" in question_text:
        records = [r for r in records if "description" in r[0].rule_id]
    elif "link" in question_text:
        records = [r for r in records if "link" in r[0].rule_id]
    elif "title" in question_text:
        records = [r for r in records if "title" in r[0].rule_id]
    weight = {"error": 0, "warning": 1, "info": 2}
    records.sort(key=lambda r: (weight.get(r[0].severity, 3), str(r[0].id)))
    sources: list[EvidenceSource] = []
    for finding, page in records:
        # The page row is already restricted to the same project and audit.
        # Metadata from JSON findings must not be interpreted as instructions.
        try:
            verified_url = normalize_url(page.url)
        except (UnsafeTarget, ValueError):
            continue
        if verified_url.host != project_domain:
            continue
        observed = ""
        if isinstance(finding.evidence, dict):
            refs = finding.evidence.get("references")
            if isinstance(refs, list) and refs:
                first = refs[0]
                if isinstance(first, dict):
                    observed = str(first.get("observed", ""))[:120]
        excerpt = f"{finding.rule_id}: {finding.summary}. {observed}".strip()[:1050]
        if len(excerpt) < 8:
            continue
        sources.append(
            EvidenceSource(
                source_id=f"finding:{finding.id}",
                kind="seo_finding",
                source_url=verified_url.value,
                finding_id=finding.id,
                captured_at=page.crawled_at,
                excerpt=excerpt,
            )
        )
        if len(sources) >= max_items:
            break
    return sources


def collect_evidence(
    session: Session,
    retriever: HybridRetriever,
    *,
    project_id: UUID,
    owner_id: UUID,
    question: str,
) -> tuple[EvidenceSource, ...]:
    check_project(session, project_id, owner_id)
    findings = _findings(session, project_id, question)
    # Each source remains separately referenced; no synthesized citations.
    result = retriever.retrieve(
        project_id=project_id,
        owner_id=owner_id,
        query=question,
        options=RetrievalOptions(
            mode="hybrid",
            top_k=4,
            candidate_k=12,
            max_context_tokens=1800,
            max_age_days=365,
        ),
    )
    sources = list(findings)
    for hit in result.hits:
        citation = hit.citation
        sources.append(
            EvidenceSource(
                source_id=citation.source_id,
                kind="indexed_page",
                source_url=citation.source_url,
                document_id=citation.document_id,
                chunk_id=citation.chunk_id,
                section_heading=citation.section_heading,
                captured_at=citation.captured_at,
                excerpt=hit.text[:1100],
            )
        )
    return tuple(sources[:12])


def _safe_no_evidence(project_id: UUID, *, uncertainty: str) -> GroundedAnswer:
    return GroundedAnswer(project_id=project_id, statements=[], sources=[], uncertainty=uncertainty)


def verify_draft(
    project_id: UUID,
    draft: AnswerDraft,
    sources: Sequence[EvidenceSource],
    *,
    model: str,
    usage: dict[str, int],
) -> GroundedAnswer:
    available = {source.source_id: source for source in sources}
    statements: list[AnswerStatement] = []
    cited: set[str] = set()
    for claim in draft.claims:
        source = available.get(claim.source_id)
        if source is None or _clean(claim.supporting_quote) not in _clean(source.excerpt):
            raise InvalidModelOutput("Answer referred to unverified source evidence")
        quote = _clean(claim.supporting_quote)
        digits = set(re.findall(r"(?<!\\w)\\d+(?:[.,]\\d+)?%?(?!\\w)", claim.statement))
        quoted_digits = set(re.findall(r"(?<!\\w)\\d+(?:[.,]\\d+)?%?(?!\\w)", quote))
        if not digits.issubset(quoted_digits):
            raise InvalidModelOutput("Answer adds a number unsupported by its quoted evidence")
        for quantifier in ("all", "every", "none"):
            if re.search(rf"\\b{quantifier}\\b", _clean(claim.statement)) and not re.search(
                rf"\\b{quantifier}\\b", quote
            ):
                raise InvalidModelOutput("Answer claims unsupported universal coverage")
        cited.add(source.source_id)
        statements.append(
            AnswerStatement(
                statement=claim.statement,
                source_id=source.source_id,
                supporting_quote=claim.supporting_quote,
            )
        )
    if not statements:
        return _safe_no_evidence(
            project_id,
            uncertainty=draft.uncertainty
            or "The available evidence does not answer this question.",
        )
    return GroundedAnswer(
        project_id=project_id,
        statements=statements,
        sources=[source for source in sources if source.source_id in cited],
        uncertainty=draft.uncertainty,
        model=model,
        token_usage=usage,
    )


def _build_request(
    question: QuestionInput,
    sources: Sequence[EvidenceSource],
) -> GenerationRequest:
    content = {
        "scope": "Verified-project indexed snapshots and recorded deterministic findings only.",
        "sources": [
            {
                "id": item.source_id,
                "kind": item.kind,
                "url": item.source_url,
                "excerpt": item.excerpt,
                "captured_at": item.captured_at.isoformat(),
            }
            for item in sources
        ],
    }
    # Token budget is enforced by the LLM adapter; reject overly large input first.
    evidence = json.dumps(content, ensure_ascii=True, separators=(",", ":"))
    if len(evidence.encode("utf-8")) > 4500:
        raise ValueError("Collected evidence exceeds question budget")
    conversation = {
        "current_question": question.question,
        "untrusted_previous_user_questions": question.previous_questions,
        "instructions": "Use only the supplied source IDs and verbatim quotes.",
    }
    return GenerationRequest(
        template_id="website_rag",
        template_version="v1",
        task=json.dumps(conversation, ensure_ascii=True),
        website_text=evidence,
        max_output_tokens=480,
    )


async def answer_question(
    project_id: UUID,
    question: QuestionInput,
    sources: Sequence[EvidenceSource],
    provider: LLMProvider,
) -> GroundedAnswer:
    if not sources:
        return _safe_no_evidence(
            project_id,
            uncertainty="No relevant indexed content or completed audit findings were found.",
        )
    # Select a bounded, exactly known subset. The model can cite only excerpts it
    # actually received; an oversized project must not fail every question.
    visible: list[EvidenceSource] = []
    request = None
    for item in sources:
        try:
            candidate = _build_request(question, (*visible, item))
        except ValueError:
            continue
        visible.append(item)
        request = candidate
    if request is None:
        return _safe_no_evidence(
            project_id, uncertainty="Indexed evidence could not fit the question budget."
        )
    completed = await provider.complete(request, schema=AnswerDraft)
    if not isinstance(completed.value, AnswerDraft):
        raise InvalidModelOutput("Answer did not match the grounding contract")
    return verify_draft(
        project_id,
        completed.value,
        visible,
        model=completed.model,
        usage=completed.usage.model_dump(),
    )
