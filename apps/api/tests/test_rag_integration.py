"""Real pgvector lifecycle tests. CI uses a local PostgreSQL container only."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from aiseoonline_api.ai_core.contracts import ProviderUnavailable
from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, parse_html
from aiseoonline_api.db.models import Project, RagChunk, RagDocument, User
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.rag.embeddings import FixtureEmbeddingProvider
from aiseoonline_api.rag.store import RagAccessDenied, RagStore


def sample_snapshot(body: str, url: str = "https://example.org/guides/clay") -> PageSnapshot:
    html = (
        "<html><body><nav>Site menu</nav><main><h1>Ceramic pottery care</h1>"
        "<p>" + body + "</p></main><footer>Site boilerplate</footer></body></html>"
    )
    return PageSnapshot(
        requested_url=url,
        final_url=url,
        captured_at=datetime.now(UTC),
        http_status=200,
        redirects=(),
        content_bytes=len(html),
        html=parse_html(html.encode(), url),
    )


@pytest.mark.integration
def test_pgvector_private_lifecycle_and_similarity_queries() -> None:
    url = os.environ.get("AISEO_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("PostgreSQL vector integration service not configured")
    engine = create_database_engine(Settings(_env_file=None, database_url=url))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    with engine.connect() as migration_connection:
                        names = inspect(migration_connection).get_table_names()
                        assert {"rag_documents", "rag_chunks"} <= set(names)
                        indexes = inspect(migration_connection).get_indexes("rag_chunks")
                        assert any(i["name"] == "ix_rag_chunks_embedding_hnsw" for i in indexes)
                        assert (
                            migration_connection.scalar(
                                text("SELECT extname FROM pg_extension WHERE extname='vector'")
                            )
                            == "vector"
                        )

                    a = User(email=f"rag-one-{uuid4().hex}@example.test")
                    b = User(email=f"rag-two-{uuid4().hex}@example.test")
                    session.add_all([a, b])
                    session.flush()
                    pa = Project(
                        owner_id=a.id, domain="example.org", verification_status="verified"
                    )
                    pb = Project(
                        owner_id=b.id, domain="example.org", verification_status="verified"
                    )
                    pending = Project(
                        owner_id=a.id, domain="other.org", verification_status="unverified"
                    )
                    session.add_all([pa, pb, pending])
                    session.flush()
                    provider = FixtureEmbeddingProvider()
                    store = RagStore(session, provider)
                    page = sample_snapshot(
                        "Clay pots are ideal for indoor houseplants. "
                        "Water ceramic planters slowly and use a tray to avoid spills. "
                        "Put indoor foliage near bright indirect light. " * 4
                    )
                    created = store.ingest_snapshot(project_id=pa.id, owner_id=a.id, snapshot=page)
                    assert created.action == "created"
                    assert created.chunks > 0
                    before_calls = provider.calls
                    second = store.ingest_snapshot(project_id=pa.id, owner_id=a.id, snapshot=page)
                    assert second.action == "unchanged"
                    assert provider.calls == before_calls
                    assert second.document_id == created.document_id
                    assert (
                        session.scalar(select(RagDocument).where(RagDocument.project_id == pa.id))
                        is not None
                    )
                    found = store.search(
                        project_id=pa.id,
                        owner_id=a.id,
                        query="clay planter indoor",
                    )
                    assert found
                    assert found[0].source_url == "https://example.org/guides/clay"
                    assert found[0].document_id == created.document_id
                    assert "Ceramic pottery care" == found[0].section_heading
                    assert "Clay pots" in found[0].text
                    assert not store.search(
                        project_id=pb.id,
                        owner_id=b.id,
                        query="clay planter indoor",
                    )

                    with pytest.raises(RagAccessDenied):
                        store.search(project_id=pa.id, owner_id=b.id, query="clay")
                    with pytest.raises(RagAccessDenied):
                        store.ingest_snapshot(project_id=pending.id, owner_id=a.id, snapshot=page)
                    with pytest.raises(RagAccessDenied):
                        store.ingest_snapshot(
                            project_id=pb.id,
                            owner_id=b.id,
                            snapshot=sample_snapshot("Other page", "https://private.example.org/"),
                        )

                    updated = store.ingest_snapshot(
                        project_id=pa.id,
                        owner_id=a.id,
                        snapshot=sample_snapshot(
                            "Stoneware bowls have a smooth glazed surface. "
                            "Use a soft cloth when cleaning ceramic bowls. " * 5
                        ),
                    )
                    assert updated.action == "updated"
                    assert updated.document_id == created.document_id
                    assert updated.content_hash != created.content_hash
                    assert all(
                        "Stoneware" in x.text
                        for x in store.search(
                            project_id=pa.id, owner_id=a.id, query="stoneware bowls"
                        )
                    )

                    class FailingEmbedding(FixtureEmbeddingProvider):
                        def embed(self, texts):
                            raise ProviderUnavailable("controlled fixture failure")

                    with pytest.raises(ProviderUnavailable):
                        RagStore(session, FailingEmbedding()).ingest_snapshot(
                            project_id=pa.id,
                            owner_id=a.id,
                            snapshot=sample_snapshot(
                                "Unexpected update should never replace the old index. " * 8
                            ),
                        )
                    # Embedding fails before any DELETE or document rewrite.
                    preserved = session.get(RagDocument, created.document_id)
                    assert preserved is not None
                    assert preserved.content_hash == updated.content_hash
                    assert store.search(project_id=pa.id, owner_id=a.id, query="stoneware bowls")

                    reindexed = RagStore(session, FixtureEmbeddingProvider("fixture-v2"))
                    rebuilt = reindexed.ingest_snapshot(
                        project_id=pa.id,
                        owner_id=a.id,
                        snapshot=sample_snapshot(
                            "Stoneware bowls have a smooth glazed surface. "
                            "Use a soft cloth when cleaning ceramic bowls. " * 5
                        ),
                    )
                    assert rebuilt.action == "reindexed"
                    assert not store.search(
                        project_id=pa.id, owner_id=a.id, query="stoneware bowls"
                    )
                    assert reindexed.search(
                        project_id=pa.id, owner_id=a.id, query="stoneware bowls"
                    )

                    with pytest.raises(RagAccessDenied):
                        reindexed.delete_document(
                            project_id=pa.id,
                            owner_id=b.id,
                            source_url="https://example.org/guides/clay",
                        )
                    assert reindexed.delete_document(
                        project_id=pa.id,
                        owner_id=a.id,
                        source_url="https://example.org/guides/clay",
                    )
                    assert not reindexed.delete_document(
                        project_id=pa.id,
                        owner_id=a.id,
                        source_url="https://example.org/guides/clay",
                    )
                    assert (
                        session.scalars(select(RagChunk).where(RagChunk.project_id == pa.id)).all()
                        == []
                    )
                    assert (
                        reindexed.search(project_id=pa.id, owner_id=a.id, query="stoneware bowls")
                        == []
                    )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
