"""Controlled PostgreSQL retrieval evaluation and strict tenant isolation.

All documents are synthetic fixtures; CI never crawls remote sites or calls paid APIs.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, parse_html
from aiseoonline_api.db.models import Project, User
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.rag.embeddings import FixtureEmbeddingProvider
from aiseoonline_api.rag.retrieval import HybridRetriever, RetrievalOptions
from aiseoonline_api.rag.store import RagAccessDenied, RagStore

DATASET = Path(__file__).parent / "fixtures" / "rag_retrieval_v1.json"


def snapshot(url: str, heading: str, body: str, *, days_old: int = 0) -> PageSnapshot:
    markup = f"<html><body><main><h1>{heading}</h1><p>{body}</p></main></body></html>"
    return PageSnapshot(
        requested_url=url,
        final_url=url,
        captured_at=datetime.now(UTC) - timedelta(days=days_old),
        http_status=200,
        redirects=(),
        content_bytes=len(markup),
        html=parse_html(markup.encode("utf-8"), url),
    )


class BackwardsReranker:
    def reorder(self, query: str, hits: tuple) -> list[UUID]:
        return [item.citation.chunk_id for item in reversed(hits)]


class ForgedReranker:
    def reorder(self, query: str, hits: tuple) -> list[UUID]:
        return [uuid4() for _ in hits]


@pytest.mark.integration
def test_pgvector_keyword_hybrid_retrieval_and_versioned_evaluation() -> None:
    url = os.getenv("AISEO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL integration URL is not configured")
    evaluation = json.loads(DATASET.read_text(encoding="utf-8"))
    assert evaluation["version"] == "rag-retrieval-v1"
    engine = create_database_engine(Settings(_env_file=None, database_url=url))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    with engine.connect() as inspect_connection:
                        indexes = inspect(inspect_connection).get_indexes("rag_chunks")
                        assert any(x["name"] == "ix_rag_chunks_english_fts" for x in indexes)
                        assert (
                            inspect_connection.scalar(
                                text("SELECT extname FROM pg_extension WHERE extname='vector'")
                            )
                            == "vector"
                        )

                    owner = User(email=f"rag-hybrid-{uuid4().hex}@example.test")
                    other = User(email=f"rag-other-{uuid4().hex}@example.test")
                    session.add_all([owner, other])
                    session.flush()
                    project = Project(
                        owner_id=owner.id, domain="example.org", verification_status="verified"
                    )
                    foreign_project = Project(
                        owner_id=other.id, domain="example.org", verification_status="verified"
                    )
                    unverified = Project(
                        owner_id=owner.id,
                        domain="unverified.org",
                        verification_status="unverified",
                    )
                    session.add_all([project, foreign_project, unverified])
                    session.flush()

                    provider = FixtureEmbeddingProvider()
                    store = RagStore(session, provider)
                    documents: dict[str, UUID] = {}
                    for row in evaluation["documents"]:
                        inserted = store.ingest_snapshot(
                            project_id=project.id,
                            owner_id=owner.id,
                            document_type=row["document_type"],
                            snapshot=snapshot(row["url"], row["heading"], row["body"]),
                        )
                        assert inserted.action == "created"
                        documents[row["id"]] = inserted.document_id

                    # Duplicate private content in another project can never cross retrieval.
                    other_entry = evaluation["documents"][0]
                    foreign = store.ingest_snapshot(
                        project_id=foreign_project.id,
                        owner_id=other.id,
                        snapshot=snapshot(
                            other_entry["url"], other_entry["heading"], other_entry["body"]
                        ),
                        document_type="guide",
                    )
                    assert foreign.document_id not in set(documents.values())
                    retriever = HybridRetriever(session, provider)
                    top_three_recall = 0
                    reciprocal_ranks: list[float] = []
                    for case in evaluation["queries"]:
                        report = retriever.retrieve(
                            project_id=project.id,
                            owner_id=owner.id,
                            query=case["query"],
                            options=RetrievalOptions(top_k=3, candidate_k=10),
                        )
                        cited = [hit.citation.document_id for hit in report.hits]
                        assert all(hit.citation.project_id == project.id for hit in report.hits)
                        assert foreign.document_id not in cited
                        assert all(
                            hit.citation.source_id
                            == f"rag:{hit.citation.document_id}:{hit.citation.chunk_id}"
                            for hit in report.hits
                        )
                        assert report.context_budget_used <= report.context_budget_limit
                        relevant = {documents[id_] for id_ in case["relevant_ids"]}
                        if relevant.intersection(cited):
                            top_three_recall += 1
                        rank = next(
                            (i for i, doc_id in enumerate(cited, 1) if doc_id in relevant), None
                        )
                        reciprocal_ranks.append(1.0 / rank if rank else 0)
                    recall_3 = top_three_recall / len(evaluation["queries"])
                    mrr_3 = sum(reciprocal_ranks) / len(reciprocal_ranks)
                    # These numbers are observed using the labeled fixture and
                    # explicitly asserted, not claimed as live search benchmarks.
                    print(
                        f"RAG synthetic fixture {evaluation['version']}: "
                        f"Recall@3={recall_3:.3f}, MRR@3={mrr_3:.3f}"
                    )
                    assert recall_3 >= 0.75, f"Hybrid Recall@3={recall_3:.3f}"
                    assert mrr_3 >= 0.50, f"Hybrid MRR@3={mrr_3:.3f}"

                    first = evaluation["queries"][0]["query"]
                    before_calls = provider.calls
                    keyword_only = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query=first,
                        options=RetrievalOptions(mode="keyword", top_k=3),
                    )
                    assert provider.calls == before_calls, "Keyword search must not embed"
                    assert keyword_only.hits, "PostgreSQL FTS must return a real match"
                    assert all(h.keyword_rank is not None for h in keyword_only.hits)
                    semantic_only = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query=first,
                        options=RetrievalOptions(mode="semantic", min_semantic_similarity=0.1),
                    )
                    assert semantic_only.hits
                    assert all(h.semantic_similarity is not None for h in semantic_only.hits)

                    types = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="pgvector HNSW cosine",
                        options=RetrievalOptions(mode="keyword", document_types=("reference",)),
                    )
                    assert types.hits
                    assert all(hit.document_type == "reference" for hit in types.hits)
                    excluded = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="pgvector HNSW cosine",
                        options=RetrievalOptions(mode="keyword", document_types=("guide",)),
                    )
                    assert all(hit.document_type == "guide" for hit in excluded.hits)

                    with pytest.raises(RagAccessDenied):
                        retriever.retrieve(
                            project_id=project.id, owner_id=other.id, query="ceramic planter"
                        )
                    with pytest.raises(RagAccessDenied):
                        retriever.retrieve(
                            project_id=unverified.id, owner_id=owner.id, query="ceramic planter"
                        )
                    # Future-dated content is not evidence of a completed historical crawl.
                    in_future = store.ingest_snapshot(
                        project_id=project.id,
                        owner_id=owner.id,
                        document_type="guide",
                        snapshot=snapshot(
                            "https://example.org/guides/future-claims",
                            "Future article",
                            "Unpublished future article content",
                            days_old=-60,
                        ),
                    )
                    future_results = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="unpublished future article",
                        options=RetrievalOptions(mode="keyword"),
                    )
                    assert in_future.document_id not in {
                        hit.citation.document_id for hit in future_results.hits
                    }
                    no_cross_project = retriever.retrieve(
                        project_id=foreign_project.id,
                        owner_id=other.id,
                        query="pgvector HNSW cosine",
                        options=RetrievalOptions(mode="keyword"),
                    )
                    assert not no_cross_project.hits
                    assert all(
                        row.citation.document_id == foreign.document_id
                        for row in retriever.retrieve(
                            project_id=foreign_project.id,
                            owner_id=other.id,
                            query="ceramic planter",
                            options=RetrievalOptions(mode="keyword"),
                        ).hits
                    )

                    # Stale data is omitted even when its lexical content matches.
                    stale_doc = evaluation["documents"][1]
                    store.ingest_snapshot(
                        project_id=project.id,
                        owner_id=owner.id,
                        document_type="guide",
                        snapshot=snapshot(
                            stale_doc["url"], stale_doc["heading"], stale_doc["body"], days_old=70
                        ),
                        force=True,
                    )
                    stale = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="robots disallow crawler",
                        options=RetrievalOptions(mode="keyword", max_age_days=14),
                    )
                    assert documents["robots"] not in {
                        item.citation.document_id for item in stale.hits
                    }

                    # Distinct conflicting claims must remain separately cited; retrieval
                    # must not invent a consensus or silently choose one as fact.
                    conflict_urls = [
                        "https://example.org/guides/returns-14",
                        "https://example.org/guides/returns-30",
                    ]
                    for claimed_days, target in zip((14, 30), conflict_urls, strict=True):
                        store.ingest_snapshot(
                            project_id=project.id,
                            owner_id=owner.id,
                            document_type="guide",
                            snapshot=snapshot(
                                target,
                                "Return policy",
                                f"Our return policy allows {claimed_days} days for returns.",
                            ),
                        )
                    conflicts = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="return policy",
                        options=RetrievalOptions(mode="keyword", top_k=5),
                    )
                    conflict_hits = [
                        hit for hit in conflicts.hits if hit.citation.source_url in conflict_urls
                    ]
                    assert len(conflict_hits) == 2
                    assert len({h.citation.source_id for h in conflict_hits}) == 2
                    assert any("14 days" in h.text for h in conflict_hits)
                    assert any("30 days" in h.text for h in conflict_hits)

                    no_match = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="xylophone quantum orbit",
                        options=RetrievalOptions(mode="keyword"),
                    )
                    assert no_match.hits == ()
                    high_threshold = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="ceramic planter watering",
                        options=RetrievalOptions(mode="hybrid", min_fused_score=0.9),
                    )
                    assert high_threshold.hits == ()
                    tiny_context = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="ceramic planter watering",
                        options=RetrievalOptions(mode="keyword", max_context_tokens=200),
                    )
                    assert tiny_context.context_budget_used <= 200
                    assert all(len(hit.text.encode()) <= 200 for hit in tiny_context.hits)

                    # Re-ranking may only reorder retrieved citations.
                    reversed_result = HybridRetriever(
                        session, provider, reranker=BackwardsReranker()
                    ).retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="ceramic planter watering",
                        options=RetrievalOptions(mode="keyword"),
                    )
                    assert reversed_result.hits
                    with pytest.raises(ValueError, match="permutation"):
                        HybridRetriever(session, provider, reranker=ForgedReranker()).retrieve(
                            project_id=project.id,
                            owner_id=owner.id,
                            query="ceramic planter watering",
                            options=RetrievalOptions(mode="keyword"),
                        )

                    # Deduplication of identical excerpt text from distinct documents
                    # retains a real citation for the first occurrence.
                    duplicate = store.ingest_snapshot(
                        project_id=project.id,
                        owner_id=owner.id,
                        document_type="guide",
                        snapshot=snapshot(
                            "https://example.org/guides/duplicate-ceramic",
                            evaluation["documents"][0]["heading"],
                            evaluation["documents"][0]["body"],
                        ),
                    )
                    assert duplicate.document_id != documents["clay"]
                    deduped = retriever.retrieve(
                        project_id=project.id,
                        owner_id=owner.id,
                        query="ceramic planter watering",
                        options=RetrievalOptions(mode="keyword", candidate_k=20),
                    )
                    assert deduped.duplicate_chunks_removed >= 1
                    assert len({x.citation.content_hash for x in deduped.hits}) == len(deduped.hits)
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
