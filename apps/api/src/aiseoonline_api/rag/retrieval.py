"""Evidence-preserving, verified-owner PostgreSQL hybrid retrieval.

No HTTP route and no LLM calls. SQLAlchemy owns parameters and caller owns commit.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, literal_column, select
from sqlalchemy.orm import Session

from aiseoonline_api.db.models import Project, RagChunk, RagDocument
from aiseoonline_api.rag.embeddings import EmbeddingProvider, validate_vectors
from aiseoonline_api.rag.store import RagAccessDenied

DocumentType = Literal["web_page", "guide", "reference"]
RetrievalMode = Literal["hybrid", "semantic", "keyword"]
_ENGLISH = literal_column("'english'::regconfig")
_ALLOWED_TYPES = frozenset(("web_page", "guide", "reference"))


class RetrievalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=10)
    candidate_k: int = Field(default=20, ge=5, le=50)
    max_context_tokens: int = Field(default=2400, ge=200, le=12000)
    min_semantic_similarity: float = Field(default=0.35, ge=-1, le=1)
    min_keyword_rank: float = Field(default=0.0, ge=0, le=1)
    min_fused_score: float = Field(default=0.015, ge=0, le=1)
    rrf_k: int = Field(default=60, ge=1, le=200)
    max_age_days: int | None = Field(default=None, ge=1, le=3650)
    document_types: tuple[DocumentType, ...] = ("web_page", "guide", "reference")

    @model_validator(mode="after")
    def check_options(self) -> "RetrievalOptions":
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be at least top_k")
        if not self.document_types or len(set(self.document_types)) != len(self.document_types):
            raise ValueError("Specify a nonempty, unique document type filter")
        return self


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    project_id: UUID
    document_id: UUID
    chunk_id: UUID
    source_url: str
    section_heading: str | None
    content_hash: str
    captured_at: datetime


class RetrievedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    citation: Citation
    text: str
    document_type: DocumentType
    access_scope: Literal["owner_only"]
    fused_score: float = Field(ge=0)
    semantic_similarity: float | None = None
    keyword_rank: float | None = None
    semantic_position: int | None = None
    keyword_position: int | None = None


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hits: tuple[RetrievedEvidence, ...]
    candidate_count: int
    duplicate_chunks_removed: int
    context_budget_used: int
    context_budget_limit: int
    measurement: Literal["utf8_bytes_upper_bound"] = "utf8_bytes_upper_bound"


class Reranker(Protocol):
    """A reranker may reorder IDs only, never invent citations or change source content."""

    def reorder(self, query: str, hits: tuple[RetrievedEvidence, ...]) -> Sequence[UUID]: ...


def reciprocal_rank_fusion(
    semantic: Sequence[UUID], keyword: Sequence[UUID], *, k: int = 60,
) -> dict[UUID, float]:
    if k < 1:
        raise ValueError("RRF offset must be positive")
    scores: dict[UUID, float] = {}
    for ranked in (semantic, keyword):
        for position, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position)
    return scores


class HybridRetriever:
    def __init__(
        self, session: Session, provider: EmbeddingProvider, *,
        reranker: Reranker | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.reranker = reranker

    def _check_owner(self, project_id: UUID, owner_id: UUID) -> None:
        authorized = self.session.scalar(
            select(Project.id).where(
                Project.id == project_id,
                Project.owner_id == owner_id,
                Project.verification_status == "verified",
            )
        )
        if authorized is None:
            raise RagAccessDenied("Verified project ownership required")

    def retrieve(
        self, *, project_id: UUID, owner_id: UUID,
        query: str, options: RetrievalOptions | None = None,
    ) -> RetrievalResult:
        # Auth is first; no embeddings, SQL search, or project-existence leak on denial.
        self._check_owner(project_id, owner_id)
        config = options or RetrievalOptions()
        cleaned = query.strip()
        if not 3 <= len(cleaned) <= 800:
            raise ValueError("Query must be 3–800 characters")
        spec = self.provider.spec
        filters = [
            Project.id == project_id,
            Project.owner_id == owner_id,
            Project.verification_status == "verified",
            RagDocument.project_id == project_id,
            RagChunk.project_id == project_id,
            RagDocument.embedding_provider == spec.provider,
            RagDocument.embedding_model == spec.model,
            RagDocument.embedding_version == spec.version,
            RagDocument.embedding_dimensions == spec.dimensions,
            RagDocument.access_scope == "owner_only",
            RagDocument.document_type.in_(config.document_types),
        ]
        if config.max_age_days is not None:
            filters.append(
                RagDocument.captured_at >= datetime.now(UTC) - timedelta(
                    days=config.max_age_days
                )
            )
        # Same project, owner and version predicates apply to BOTH retrieval channels.
        stmt = (
            select(RagChunk, RagDocument)
            .join(
                RagDocument,
                (RagDocument.id == RagChunk.document_id)
                & (RagDocument.project_id == RagChunk.project_id),
            )
            .join(Project, Project.id == RagDocument.project_id)
            .where(*filters)
        )
        collected: dict[UUID, tuple[RagChunk, RagDocument]] = {}
        semantic_order: list[UUID] = []
        keyword_order: list[UUID] = []
        similarities: dict[UUID, float] = {}
        keywords: dict[UUID, float] = {}

        if config.mode in ("hybrid", "semantic"):
            # Embedding provider is never invoked for keyword-only search.
            vector = self.provider.embed([cleaned])[0]
            validate_vectors([vector], 1)
            distance = RagChunk.embedding.cosine_distance(vector)
            rows = self.session.execute(
                stmt.add_columns(distance)
                .where(distance <= 1.0 - config.min_semantic_similarity)
                .order_by(distance, RagChunk.id)
                .limit(config.candidate_k)
            )
            for row in rows:
                chunk, document, dis = cast(tuple[RagChunk, RagDocument, float], row)
                semantic_order.append(chunk.id)
                collected[chunk.id] = (chunk, document)
                similarities[chunk.id] = max(-1.0, min(1.0, 1.0 - float(dis)))

        if config.mode in ("hybrid", "keyword"):
            # Both arguments use a fixed regconfig; plain query escapes TS query operators.
            tsvector = func.to_tsvector(
                _ENGLISH,
                func.coalesce(RagChunk.heading, literal_column("''"))
                + literal_column("' '")
                + RagChunk.text,
            )
            tsquery = func.plainto_tsquery(_ENGLISH, cleaned)
            rank = func.ts_rank_cd(tsvector, tsquery)
            rows = self.session.execute(
                stmt.add_columns(rank)
                .where(tsvector.op("@@")(tsquery), rank > config.min_keyword_rank)
                .order_by(rank.desc(), RagChunk.id)
                .limit(config.candidate_k)
            )
            for row in rows:
                chunk, document, score = cast(tuple[RagChunk, RagDocument, float], row)
                keyword_order.append(chunk.id)
                collected[chunk.id] = (chunk, document)
                keywords[chunk.id] = float(score)

        fused = reciprocal_rank_fusion(semantic_order, keyword_order, k=config.rrf_k)
        ranked = sorted(
            (chunk_id for chunk_id in fused if fused[chunk_id] >= config.min_fused_score),
            key=lambda chunk_id: (-fused[chunk_id], str(chunk_id)),
        )
        semantic_positions = {id_: i for i, id_ in enumerate(semantic_order, start=1)}
        keyword_positions = {id_: i for i, id_ in enumerate(keyword_order, start=1)}
        candidates: list[RetrievedEvidence] = []
        duplicate_count = 0
        fingerprints: set[str] = set()
        for chunk_id in ranked:
            chunk, doc = collected[chunk_id]
            if chunk.content_hash in fingerprints:
                duplicate_count += 1
                continue
            fingerprints.add(chunk.content_hash)
            candidates.append(
                RetrievedEvidence(
                    citation=Citation(
                        source_id=f"rag:{doc.id}:{chunk.id}",
                        project_id=project_id,
                        document_id=doc.id,
                        chunk_id=chunk.id,
                        source_url=doc.source_url,
                        section_heading=chunk.heading,
                        content_hash=chunk.content_hash,
                        captured_at=doc.captured_at,
                    ),
                    text=chunk.text,
                    document_type=doc.document_type,
                    access_scope="owner_only",
                    fused_score=fused[chunk_id],
                    semantic_similarity=similarities.get(chunk_id),
                    keyword_rank=keywords.get(chunk_id),
                    semantic_position=semantic_positions.get(chunk_id),
                    keyword_position=keyword_positions.get(chunk_id),
                )
            )

        if self.reranker is not None and candidates:
            ids = self.reranker.reorder(cleaned, tuple(candidates))
            actual = [item.citation.chunk_id for item in candidates]
            if len(ids) != len(actual) or set(ids) != set(actual):
                raise ValueError("Reranker must return a permutation of actual candidate IDs")
            mapped = {item.citation.chunk_id: item for item in candidates}
            candidates = [mapped[id_] for id_ in ids]

        # UTF-8 bytes are a conservative *upper bound* on most tokenizers, not a
        # promise of exact model token counts. Never truncate evidence or fill with noise.
        chosen: list[RetrievedEvidence] = []
        used = 0
        for item in candidates:
            charge = len(item.text.encode("utf-8"))
            charge += len(item.citation.source_url.encode("utf-8"))
            charge += len((item.citation.section_heading or "").encode("utf-8"))
            if used + charge > config.max_context_tokens:
                continue
            chosen.append(item)
            used += charge
            if len(chosen) >= config.top_k:
                break
        return RetrievalResult(
            hits=tuple(chosen), candidate_count=len(ranked),
            duplicate_chunks_removed=duplicate_count,
            context_budget_used=used,
            context_budget_limit=config.max_context_tokens,
        )
