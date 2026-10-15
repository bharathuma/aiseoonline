"""Private transaction-scoped RAG ingestion and vector retrieval.

Callers supply a SQLAlchemy Session and own commit/rollback. No public API route exists.
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from aiseoonline_api.crawler import CrawlSession, PageSnapshot, normalize_url
from aiseoonline_api.db.models import Project, RagChunk, RagDocument
from aiseoonline_api.rag.chunking import chunks_from_sections, hash_text
from aiseoonline_api.rag.embeddings import (
    DIMENSIONS,
    EmbeddingProvider,
    EmbeddingSpec,
    validate_vectors,
)


class RagAccessDenied(PermissionError):
    """No document state or cross-project data is disclosed."""


class RagContentError(ValueError):
    """Page evidence cannot be safely or usefully indexed."""


class IngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    action: str
    chunks: int
    content_hash: str


class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    chunk_id: UUID
    source_url: str
    section_heading: str | None
    text: str
    content_hash: str
    captured_at: datetime
    similarity: float = Field(ge=-1.01, le=1.01)


class RagStore:
    def __init__(
        self,
        session: Session,
        embedding: EmbeddingProvider,
        *,
        chunk_size: int = 750,
        overlap: int = 90,
        max_chunks: int = 24,
    ) -> None:
        if not (200 <= chunk_size <= 2000 and 0 <= overlap < chunk_size // 2):
            raise ValueError("Invalid RAG chunk settings")
        if not 1 <= max_chunks <= 24:
            raise ValueError("RAG chunk count exceeds ingestion budget")
        self.session = session
        self.embedding = embedding
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.max_chunks = max_chunks
        if embedding.spec.dimensions != DIMENSIONS:
            raise ValueError("Embedding provider dimensions incompatible with vector index")

    def _authorized_project(self, project_id: UUID, owner_id: UUID) -> Project:
        project = self.session.scalar(
            select(Project).where(
                Project.id == project_id,
                Project.owner_id == owner_id,
                Project.verification_status == "verified",
            )
        )
        if project is None:
            raise RagAccessDenied("Verified project ownership required")
        return project

    @staticmethod
    def _allowed_page(snapshot: PageSnapshot, project: Project) -> str:
        if snapshot.http_status != 200 or snapshot.captured_at.tzinfo is None:
            raise RagContentError("Only successful, timestamped page snapshots may be indexed")
        try:
            requested = normalize_url(snapshot.requested_url)
            final = normalize_url(snapshot.final_url)
        except ValueError:
            raise RagContentError("Snapshot has invalid source URL") from None
        if requested.host != project.domain or final.host != project.domain:
            raise RagAccessDenied("Page is outside verified project hostname")
        if requested.origin != final.origin:
            raise RagContentError("Only same-origin fetched snapshots may be indexed")
        return final.value

    def ingest_url(self, *, project_id: UUID, owner_id: UUID, url: str) -> IngestionResult:
        """Always verify ownership *before* any network fetch."""
        project = self._authorized_project(project_id, owner_id)
        target = normalize_url(url)
        if target.host != project.domain:
            raise RagAccessDenied("Page is outside verified project hostname")
        return self.ingest_snapshot(
            project_id=project_id,
            owner_id=owner_id,
            snapshot=CrawlSession(target.value).fetch_page(),
        )

    def ingest_snapshot(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        snapshot: PageSnapshot,
        force: bool = False,
        document_type: str = "web_page",
    ) -> IngestionResult:
        project = self._authorized_project(project_id, owner_id)
        if document_type not in ("web_page", "guide", "reference"):
            raise RagContentError("Unsupported document type")
        source = self._allowed_page(snapshot, project)
        if not snapshot.html.content_sections:
            raise RagContentError("Snapshot contains no cleaned body sections")
        if sum(len(s.text) for s in snapshot.html.content_sections) > 18000:
            raise RagContentError("Page exceeds cleaned-content ingestion limit")
        try:
            chunks = chunks_from_sections(
                snapshot.html.content_sections,
                size=self.chunk_size,
                overlap=self.overlap,
                max_chunks=self.max_chunks,
            )
        except ValueError as exc:
            raise RagContentError("Snapshot cannot fit the chunk budget") from exc
        body = "\n".join((chunk.heading or "") + "\n" + chunk.text for chunk in chunks)
        content_hash = hash_text(f"rag-extraction-v1:{self.chunk_size}:{self.overlap}\n" + body)
        spec = self.embedding.spec
        record = self.session.scalar(
            select(RagDocument)
            .where(RagDocument.project_id == project_id, RagDocument.source_url == source)
            .with_for_update()
        )
        same_spec = bool(
            record is not None
            and record.embedding_provider == spec.provider
            and record.embedding_model == spec.model
            and record.embedding_version == spec.version
            and record.embedding_dimensions == spec.dimensions
            and record.document_type == document_type
            and record.access_scope == "owner_only"
        )
        if record is not None and same_spec and record.content_hash == content_hash and not force:
            count = (
                self.session.query(RagChunk)
                .filter(
                    RagChunk.project_id == project_id,
                    RagChunk.document_id == record.id,
                )
                .count()
            )
            return IngestionResult(
                document_id=record.id,
                action="unchanged",
                chunks=count,
                content_hash=content_hash,
            )

        # Embed first; a failure must never delete previously committed indexed content.
        vectors: list[list[float]] = []
        for offset in range(0, len(chunks), 8):
            batch = chunks[offset : offset + 8]
            vectors.extend(self.embedding.embed([item.text for item in batch]))
        validate_vectors(vectors, len(chunks))

        if record is None:
            record = RagDocument(
                project_id=project_id,
                source_url=source,
                document_type=document_type,
                access_scope="owner_only",
                content_hash=content_hash,
                embedding_provider=spec.provider,
                embedding_model=spec.model,
                embedding_version=spec.version,
                embedding_dimensions=spec.dimensions,
                captured_at=snapshot.captured_at,
            )
            self.session.add(record)
            self.session.flush()
            action = "created"
        else:
            self.session.execute(
                delete(RagChunk).where(
                    RagChunk.project_id == project_id, RagChunk.document_id == record.id
                )
            )
            record.document_type = document_type
            record.access_scope = "owner_only"
            record.content_hash = content_hash
            record.embedding_provider = spec.provider
            record.embedding_model = spec.model
            record.embedding_version = spec.version
            record.embedding_dimensions = spec.dimensions
            record.captured_at = snapshot.captured_at
            action = "reindexed" if force or not same_spec else "updated"

        for chunk, embedding in zip(chunks, vectors, strict=True):
            self.session.add(
                RagChunk(
                    project_id=project_id,
                    document_id=record.id,
                    ordinal=chunk.ordinal,
                    heading=chunk.heading,
                    text=chunk.text,
                    content_hash=chunk.content_hash,
                    embedding=embedding,
                )
            )
        self.session.flush()
        return IngestionResult(
            document_id=record.id,
            action=action,
            chunks=len(chunks),
            content_hash=content_hash,
        )

    def delete_document(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        source_url: str,
    ) -> bool:
        self._authorized_project(project_id, owner_id)
        source = normalize_url(source_url).value
        row = self.session.scalar(
            select(RagDocument).where(
                RagDocument.project_id == project_id, RagDocument.source_url == source
            )
        )
        if row is None:
            return False
        self.session.delete(row)
        self.session.flush()
        return True

    def search(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        query: str,
        limit: int = 5,
    ) -> list[SearchHit]:
        self._authorized_project(project_id, owner_id)
        if not 1 <= limit <= 10 or not 3 <= len(query.strip()) <= 800:
            raise ValueError("Invalid retrieval query or result limit")
        vector = self.embedding.embed([query.strip()])[0]
        validate_vectors([vector], 1)
        spec: EmbeddingSpec = self.embedding.spec
        distance = RagChunk.embedding.cosine_distance(vector).label("distance")
        statement = (
            select(RagChunk, RagDocument, distance)
            .join(RagDocument, RagDocument.id == RagChunk.document_id)
            .join(Project, Project.id == RagChunk.project_id)
            .where(
                Project.id == project_id,
                Project.owner_id == owner_id,
                Project.verification_status == "verified",
                RagDocument.project_id == project_id,
                RagChunk.project_id == project_id,
                RagDocument.embedding_provider == spec.provider,
                RagDocument.embedding_model == spec.model,
                RagDocument.embedding_version == spec.version,
                RagDocument.embedding_dimensions == spec.dimensions,
            )
            .order_by(distance, RagChunk.id)
            .limit(limit)
        )
        results = []
        for row in self.session.execute(statement):
            chunk, doc, similarity_distance = cast(tuple[RagChunk, RagDocument, float], row)
            results.append(
                SearchHit(
                    document_id=doc.id,
                    chunk_id=chunk.id,
                    source_url=doc.source_url,
                    section_heading=chunk.heading,
                    text=chunk.text,
                    content_hash=chunk.content_hash,
                    captured_at=doc.captured_at,
                    similarity=max(-1.0, min(1.0, 1.0 - float(similarity_distance))),
                )
            )
        return results
