"""Controlled PostgreSQL and Redis tests of project-scoped website chat evidence."""

import asyncio
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy.orm import Session

from aiseoonline_api.ai_core import FixtureProvider, TokenUsage
from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, parse_html
from aiseoonline_api.db.models import AuditJob, Page, Project, SeoFinding, User
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.rag.assistant import QuestionInput, answer_question, collect_evidence
from aiseoonline_api.rag.chat_routes import reserve
from aiseoonline_api.rag.embeddings import FixtureEmbeddingProvider
from aiseoonline_api.rag.retrieval import HybridRetriever
from aiseoonline_api.rag.store import RagAccessDenied, RagStore


def page_snapshot(url: str, html: str) -> PageSnapshot:
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
def test_private_rag_answers_genuine_findings_and_blocks_other_projects() -> None:
    db_url = os.getenv("AISEO_TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("PostgreSQL integration database not configured")
    engine = create_database_engine(Settings(_env_file=None, database_url=db_url))
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
                    owner = User(email=f"private-rag-{uuid4().hex}@example.test")
                    other = User(email=f"private-rag-other-{uuid4().hex}@example.test")
                    session.add_all([owner, other])
                    session.flush()
                    project = Project(
                        owner_id=owner.id, domain="example.org", verification_status="verified"
                    )
                    foreign = Project(
                        owner_id=other.id, domain="example.org", verification_status="verified"
                    )
                    session.add_all([project, foreign])
                    session.flush()
                    content = (
                        "<html><body><main><h1>Shop ceramics</h1>"
                        "<p>Handmade ceramic planters with drainage trays and "
                        "practical indoor plant care recommendations.</p>"
                        "</main></body></html>"
                    )
                    snapshot = page_snapshot("https://example.org/shop", content)
                    fixture = FixtureEmbeddingProvider()
                    RagStore(session, fixture).ingest_snapshot(
                        project_id=project.id, owner_id=owner.id, snapshot=snapshot
                    )
                    # Persist a completed deterministic audit result with a page association.
                    job = AuditJob(project_id=project.id, status="completed")
                    session.add(job)
                    session.flush()
                    stored_page = Page(
                        project_id=project.id,
                        audit_job_id=job.id,
                        url="https://example.org/shop",
                        title="Shop ceramics",
                        http_status=200,
                    )
                    session.add(stored_page)
                    session.flush()
                    finding = SeoFinding(
                        audit_job_id=job.id,
                        page_id=stored_page.id,
                        rule_id="description.missing",
                        severity="warning",
                        summary="Missing meta description",
                        evidence={"references": [{"observed": "No description captured"}]},
                    )
                    session.add(finding)
                    session.flush()
                    question = QuestionInput(
                        project_id=project.id,
                        question="Which pages are missing meta descriptions?",
                    )
                    retrieval = HybridRetriever(session, fixture)
                    sources = collect_evidence(
                        session,
                        retrieval,
                        project_id=project.id,
                        owner_id=owner.id,
                        question=question.question,
                    )
                    matching = [s for s in sources if s.source_id == f"finding:{finding.id}"]
                    assert len(matching) == 1
                    assert matching[0].source_url == "https://example.org/shop"
                    assert matching[0].kind == "seo_finding"
                    assert len(sources) <= 12
                    fake = FixtureProvider(
                        text=json.dumps(
                            {
                                "claims": [
                                    {
                                        "statement": "The shop page is missing a meta description.",
                                        "source_id": matching[0].source_id,
                                        "supporting_quote": "Missing meta description",
                                    }
                                ],
                                "uncertainty": "Other pages without completed audits remain unknown.",
                            }
                        ),
                        usage=TokenUsage(input_tokens=120, output_tokens=50, total_tokens=170),
                    )
                    result = asyncio.run(answer_question(project.id, question, sources, fake))
                    assert len(result.statements) == 1
                    assert result.statements[0].source_id == f"finding:{finding.id}"
                    assert len(result.sources) == 1
                    assert result.sources[0].source_url == "https://example.org/shop"
                    assert "unknown" in result.uncertainty
                    with pytest.raises(RagAccessDenied):
                        collect_evidence(
                            session,
                            retrieval,
                            project_id=project.id,
                            owner_id=other.id,
                            question=question.question,
                        )
                    foreign_sources = collect_evidence(
                        session,
                        retrieval,
                        project_id=foreign.id,
                        owner_id=other.id,
                        question=question.question,
                    )
                    assert foreign_sources == ()
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.integration
def test_private_chat_budget_is_atomic_with_real_redis() -> None:
    url = os.getenv("AISEO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Redis integration service not configured")
    from datetime import UTC, datetime
    from hashlib import sha256

    peer = f"rag-fixture-{uuid4().hex}"
    peer_key = "ai:rag:peer:" + sha256(peer.encode()).hexdigest()
    day_key = "ai:rag:daily:" + datetime.now(UTC).strftime("%Y%m%d")
    with Redis.from_url(url) as redis_client:
        old = redis_client.get(day_key)
        old_ttl = redis_client.ttl(day_key)
        try:
            redis_client.delete(day_key)
            assert reserve(url, peer, 25, 50) == 1
            assert reserve(url, peer, 25, 50) == 1
            assert reserve(url, peer, 25, 50) == -1
            assert int(redis_client.get(day_key) or 0) == 50
        finally:
            redis_client.delete(peer_key, day_key)
            if old is not None:
                redis_client.set(day_key, old, ex=max(old_ttl, 1))
