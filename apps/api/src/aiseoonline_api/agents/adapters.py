"""Production adapters: verify project ownership before safe crawling or private RAG."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiseoonline_api.agents.models import AuditRequest
from aiseoonline_api.crawler import normalize_url
from aiseoonline_api.db.models import Project
from aiseoonline_api.rag.retrieval import HybridRetriever, RetrievalOptions
from aiseoonline_api.rag.store import RagAccessDenied


def project_authorizer(session: Session) -> Callable[[AuditRequest], None]:
    """Trusted backend adapter. Owner UUID must come from server authentication."""

    def authorize(request: AuditRequest) -> None:
        project = session.scalar(
            select(Project).where(
                Project.id == request.project_id,
                Project.owner_id == request.owner_id,
                Project.verification_status == "verified",
            )
        )
        if project is None:
            raise RagAccessDenied("Verified project ownership required")
        target = normalize_url(request.url)
        if target.host != project.domain:
            raise RagAccessDenied("Requested hostname is outside verified project")

    return authorize


def hybrid_rag_lookup(
    retriever: HybridRetriever,
) -> Callable[[AuditRequest, str], list[dict[str, str]]]:
    """Use the existing owner-scoped hybrid retriever, never arbitrary SQL or user IDs."""

    def lookup(request: AuditRequest, question: str) -> list[dict[str, str]]:
        result = retriever.retrieve(
            project_id=request.project_id,
            owner_id=request.owner_id,
            query=question,
            options=RetrievalOptions(
                top_k=2,
                candidate_k=8,
                max_context_tokens=700,
                max_age_days=365,
            ),
        )
        return [
            {
                "source_id": hit.citation.source_id,
                "source_url": hit.citation.source_url,
                "excerpt": hit.text[:320],
            }
            for hit in result.hits
        ]

    return lookup
