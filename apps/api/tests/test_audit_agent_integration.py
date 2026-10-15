"""Real PostgreSQL ownership + private RAG tool integration for the LangGraph agent."""

import asyncio
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from aiseoonline_api.agents.adapters import hybrid_rag_lookup, project_authorizer
from aiseoonline_api.agents.models import AuditRequest, ToolChoice
from aiseoonline_api.agents.workflow import AuditAgent
from aiseoonline_api.ai_core.contracts import ModelResult, TokenUsage
from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, parse_html
from aiseoonline_api.db.models import Project, User
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.rag.embeddings import FixtureEmbeddingProvider
from aiseoonline_api.rag.retrieval import HybridRetriever
from aiseoonline_api.rag.store import RagAccessDenied, RagStore


class RagSelectorFixture:
    def __init__(self):
        self.calls = 0

    async def complete(self, request, *, schema):
        self.calls += 1
        if schema is ToolChoice:
            available = json.loads(request.website_text)["available_tools"]
            name = "rag" if "rag" in available else "stop"
            value = ToolChoice(name=name, reason="Check existing, owner-scoped RAG evidence")
        else:
            from aiseoonline_api.agents.models import AgentDraft
            value = AgentDraft(recommendations=[], uncertainty="No supported extra claims")
        return ModelResult(
            value=value, model="fixture", cost_usd=Decimal(0),
            usage=TokenUsage(input_tokens=70, output_tokens=30, total_tokens=100),
            prompt_id=request.template_id, prompt_version=request.template_version,
        )


@pytest.mark.integration
def test_audit_agent_uses_verified_project_and_existing_rag_retriever() -> None:
    db_url = os.getenv("AISEO_TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("Local PostgreSQL integration service is not configured")
    engine = create_database_engine(Settings(_env_file=None, database_url=db_url))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                    owner = User(email=f"agent-owner-{uuid4().hex}@example.test")
                    stranger = User(email=f"agent-other-{uuid4().hex}@example.test")
                    session.add_all([owner, stranger])
                    session.flush()
                    project = Project(
                        owner_id=owner.id, domain="example.org", verification_status="verified"
                    )
                    session.add(project)
                    session.flush()
                    url = "https://example.org/seo"
                    html = (
                        '<html><body><main><h1>Clay planter care</h1>'
                        '<p>Handmade ceramic planters need drainage trays and gentle watering. '
                        'Allow the soil to dry before watering again.</p></main></body></html>'
                    )
                    data = html.encode()
                    sample = PageSnapshot(
                        requested_url=url, final_url=url,
                        captured_at=datetime.now(UTC), http_status=200,
                        redirects=(), content_bytes=len(data), html=parse_html(data, url),
                    )
                    embedding = FixtureEmbeddingProvider()
                    inserted = RagStore(session, embedding).ingest_snapshot(
                        project_id=project.id, owner_id=owner.id, snapshot=sample
                    )
                    assert inserted.action == "created"
                    provider = RagSelectorFixture()
                    actual_fetches = []

                    def fetch(page_url: str) -> PageSnapshot:
                        actual_fetches.append(page_url)
                        return sample

                    agent = AuditAgent(
                        authorize=project_authorizer(session),
                        fetch=fetch,
                        llm=provider,
                        rag_lookup=hybrid_rag_lookup(HybridRetriever(session, embedding)),
                    )
                    request = AuditRequest(
                        owner_id=owner.id, project_id=project.id, url=url,
                        max_tools=1, max_model_calls=2, use_private_rag=True,
                    )
                    report = asyncio.run(agent.run(request))
                    assert report.status == "completed", report.model_dump()
                    assert report.selected_tools == ["rag"]
                    assert len(actual_fetches) == 1
                    assert provider.calls == 2
                    assert any(t.node == "tool" and t.tool == "rag" for t in report.trace)
                    assert all(x.affected_url == url for x in report.findings)
                    assert report.website_changes_performed is False
                    print("AGENT TRACE:", json.dumps([t.model_dump() for t in report.trace]))
                    blocked = request.model_copy(update={"owner_id": stranger.id})
                    with pytest.raises(RagAccessDenied):
                        asyncio.run(agent.run(blocked))
                    assert len(actual_fetches) == 1
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
