"""Real PostgreSQL lifecycle, Celery worker invocation and LangGraph checkpoint recovery."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from aiseoonline_api.agents.adapters import project_authorizer
from aiseoonline_api.agents.execution import (
    JobConflict,
    JobUnavailable,
    authorized_job,
    cancel_job,
    claim_job,
    complete_job,
    create_job,
    overdue_jobs,
    touch_job,
)
from aiseoonline_api.agents.models import (
    AgentDraft,
    AuditRequest,
    ToolChoice,
)
from aiseoonline_api.agents.runner import execute_audit_job
from aiseoonline_api.agents.workflow import AuditAgent
from aiseoonline_api.ai_core.contracts import ModelResult, TokenUsage
from aiseoonline_api.config import Settings
from aiseoonline_api.crawler import PageSnapshot, parse_html
from aiseoonline_api.db.models import AuditJob, Project, SeoFinding, User
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.main import create_app

TARGET = "https://example.org/audit"
HTML = (
    "<html><head><link rel='canonical' href='/wrong'></head><body>"
    "<h1>Example audit heading</h1><h3>Skipped heading level</h3></body></html>"
)


def snapshot(url: str) -> PageSnapshot:
    content = HTML.encode()
    return PageSnapshot(
        requested_url=url,
        final_url=url,
        captured_at=datetime.now(UTC),
        http_status=200,
        content_bytes=len(content),
        redirects=(),
        html=parse_html(content, url),
    )


class AuditFixtureModel:
    def __init__(self):
        self.calls = 0

    async def complete(self, request, *, schema):
        self.calls += 1
        if schema is ToolChoice:
            value = ToolChoice(name="stop", reason="Enough evidence for a private report")
        elif schema is AgentDraft:
            value = AgentDraft(recommendations=[], uncertainty="No additional claims")
        else:
            raise AssertionError("Unexpected model call")
        return ModelResult(
            value=value,
            model="test-fixture",
            cost_usd=Decimal(0),
            usage=TokenUsage(input_tokens=100, output_tokens=20, total_tokens=120),
            prompt_id=request.template_id,
            prompt_version=request.template_version,
        )


def options(url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=url,
        redis_url=os.environ.get("AISEO_TEST_REDIS_URL"),
        audit_jobs_enabled=True,
        audit_dev_token="dev-only-" + "x" * 48,
        audit_dev_owner_id=uuid4(),
    )


@pytest.mark.integration
def test_job_workflow_cancellation_duplicates_reports_and_cross_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("AISEO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL service unavailable")
    settings = options(database_url)
    engine = create_database_engine(settings)
    owner_id = uuid4()
    stranger_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    try:
        with Session(engine) as session, session.begin():
            session.add_all(
                [
                    User(id=owner_id, email=f"audit-owner-{uuid4().hex}@example.test"),
                    User(id=stranger_id, email=f"audit-stranger-{uuid4().hex}@example.test"),
                ]
            )
            session.flush()
            session.add_all(
                [
                    Project(
                        id=project_id,
                        owner_id=owner_id,
                        domain="example.org",
                        verification_status="verified",
                    ),
                    Project(
                        id=other_project_id,
                        owner_id=stranger_id,
                        domain="example.org",
                        verification_status="verified",
                    ),
                ]
            )
        request = AuditRequest(
            project_id=project_id,
            owner_id=owner_id,
            url=TARGET,
            max_tools=1,
            max_model_calls=2,
            max_seconds=45,
        )
        with Session(engine) as session, session.begin():
            job, created = create_job(
                session,
                request=request,
                key="fixture-unique-abc123",
            )
            assert created
            job_id = job.id
        with Session(engine) as session, session.begin():
            same, created = create_job(session, request=request, key="fixture-unique-abc123")
            assert not created and same.id == job_id
            with pytest.raises(JobConflict):
                create_job(
                    session,
                    request=request.model_copy(update={"max_tools": 0}),
                    key="fixture-unique-abc123",
                )
            with pytest.raises(JobUnavailable):
                authorized_job(session, job_id, stranger_id)
        calls = {"fetch": 0}
        fixture = AuditFixtureModel()

        def fetch(url: str) -> PageSnapshot:
            calls["fetch"] += 1
            return snapshot(url)

        result = execute_audit_job(
            job_id,
            settings=settings,
            provider_factory=lambda _: fixture,
            fetch=fetch,
        )
        assert result == "completed"
        assert fixture.calls > 0
        assert calls["fetch"] == 1
        assert (
            execute_audit_job(
                job_id,
                settings=settings,
                provider_factory=lambda _: fixture,
                fetch=fetch,
            )
            == "not_claimed"
        )
        assert calls["fetch"] == 1
        with Session(engine) as session:
            record = authorized_job(session, job_id, owner_id)
            assert record.status == "completed"
            assert record.progress_percent == 100
            assert record.report_data is not None
            assert record.report_data["recommendations"] == []
            assert record.report_data["findings"]
            issues = session.scalars(
                select(SeoFinding).where(SeoFinding.audit_job_id == job_id)
            ).all()
            assert len(issues) == len(record.report_data["findings"])
            assert all(item.evidence["kind"] == "deterministic" for item in issues)
            assert all(item.affected_url == TARGET for item in issues)

        # A queued cancellation never executes the model or crawler.
        with Session(engine) as session, session.begin():
            to_cancel, _ = create_job(session, request=request, key="cancel-queue-456")
            cancelled_id = to_cancel.id
            cancelled = cancel_job(session, cancelled_id, owner_id)
            assert cancelled.status == "cancelled"
        assert (
            execute_audit_job(
                cancelled_id,
                settings=settings,
                provider_factory=lambda _: fixture,
                fetch=fetch,
            )
            == "not_claimed"
        )
        with Session(engine) as session, session.begin():
            stale, _ = create_job(session, request=request, key="lease-expired-123")
            lease_id = stale.id
        with Session(engine) as session, session.begin():
            claimed = claim_job(session, lease_id)
            assert claimed is not None and claimed[1] == 1
            stale = session.get(AuditJob, lease_id)
            assert stale is not None
            stale.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        with Session(engine) as session, session.begin():
            recovered = overdue_jobs(session)
            assert lease_id in recovered
        with Session(engine) as session, session.begin():
            resumed = claim_job(session, lease_id)
            assert resumed is not None and resumed[1] == 2
            assert not touch_job(session, lease_id, 1)
            assert touch_job(session, lease_id, 2, step="checks")
            cancel_job(session, lease_id, owner_id)
            assert not touch_job(session, lease_id, 2)
            assert complete_job(session, lease_id, 2, report=None, outcome="failed")
            assert session.get(AuditJob, lease_id).status == "cancelled"

        with Session(engine) as session, session.begin():
            pending, _ = create_job(session, request=request, key="orphan-limit-999")
            pending_id = pending.id
            pending.status = "running"
            pending.attempts = 3
            pending.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            pending.started_at = datetime.now(UTC)
        with Session(engine) as session, session.begin():
            assert pending_id not in overdue_jobs(session)
            assert session.get(AuditJob, pending_id).status == "failed"
    finally:
        with Session(engine) as session, session.begin():
            for user_id in (owner_id, stranger_id):
                user = session.get(User, user_id)
                if user:
                    session.delete(user)
        engine.dispose()


@pytest.mark.integration
def test_persistent_langgraph_checkpoint_resumes_without_refetching() -> None:
    db_url = os.environ.get("AISEO_TEST_DATABASE_URL")
    if not db_url:
        pytest.skip("PostgreSQL service unavailable")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    settings = options(db_url)
    engine = create_database_engine(settings)
    owner_id, project_id = uuid4(), uuid4()
    try:
        with Session(engine) as session, session.begin():
            session.add(User(id=owner_id, email=f"checkpoint-{uuid4().hex}@example.test"))
            session.flush()
            session.add(
                Project(
                    id=project_id,
                    owner_id=owner_id,
                    domain="example.org",
                    verification_status="verified",
                )
            )
        req = AuditRequest(
            project_id=project_id,
            owner_id=owner_id,
            url=TARGET,
            max_tools=0,
            max_model_calls=1,
        )
        calls = {"fetch": 0, "checks": 0}

        def fetch(url: str) -> PageSnapshot:
            calls["fetch"] += 1
            return snapshot(url)

        def interrupted(step: str) -> None:
            if step == "checks":
                calls["checks"] += 1
                raise RuntimeError("controlled checkpoint interruption")

        async def verify() -> None:
            connection_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
            async with AsyncPostgresSaver.from_conn_string(connection_url) as checkpoint:
                await checkpoint.setup()
                thread_id = "audit:test:" + uuid4().hex
                with Session(engine) as session:
                    first = AuditAgent(
                        authorize=project_authorizer(session),
                        llm=AuditFixtureModel(),
                        fetch=fetch,
                        on_step=interrupted,
                    )
                    with pytest.raises(RuntimeError, match="checkpoint interruption"):
                        await first.run(req, checkpointer=checkpoint, thread_id=thread_id)
                    second = AuditAgent(
                        authorize=project_authorizer(session),
                        llm=AuditFixtureModel(),
                        fetch=fetch,
                    )
                    report = await second.run(req, checkpointer=checkpoint, thread_id=thread_id)
                    assert report.status == "completed"
                    assert report.findings
                    assert calls["fetch"] == 1
                    assert calls["checks"] == 1
                    assert (
                        await second.run(req, checkpointer=checkpoint, thread_id=thread_id)
                        == report
                    )

        asyncio.run(verify())
    finally:
        with Session(engine) as session, session.begin():
            user = session.get(User, owner_id)
            if user:
                session.delete(user)
        engine.dispose()


@pytest.mark.integration
def test_private_audit_api_authorization_polling_cancellation_and_exports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.environ.get("AISEO_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL service unavailable")
    from aiseoonline_api.agents import routes as audit_routes

    owner_id, project_id = uuid4(), uuid4()
    token = "local-dev-token-" + "x" * 48
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://127.0.0.1:6379/0",
        audit_jobs_enabled=True,
        audit_dev_token=token,
        audit_dev_owner_id=owner_id,
        openai_api_key="offline-only",
        llm_input_usd_per_million=Decimal("1"),
        llm_output_usd_per_million=Decimal("2"),
    )
    engine = create_database_engine(settings)
    delivered: list[str] = []

    class FakeQueue:
        def send_task(self, name: str, args: list[str], task_id: str):
            assert name == "aiseoonline.audit.execute"
            assert args == [task_id]
            delivered.append(task_id)

    monkeypatch.setattr(audit_routes, "reserve_daily_budget", lambda *a: 1)
    monkeypatch.setattr(audit_routes, "create_celery_app", lambda s: FakeQueue())
    try:
        with Session(engine) as session, session.begin():
            session.add(User(id=owner_id, email=f"audit-http-{uuid4().hex}@example.test"))
            session.flush()
            session.add(
                Project(
                    id=project_id,
                    owner_id=owner_id,
                    domain="example.org",
                    verification_status="verified",
                )
            )
        app = create_app(settings)
        headers = {
            "x-dev-audit-token": token,
            "Idempotency-Key": "http-private-fixture-001",
        }
        with TestClient(app) as client:
            payload = {"project_id": str(project_id), "url": TARGET}
            denied = client.post("/api/v1/internal/audits", json=payload)
            assert denied.status_code in (404, 422)
            response = client.post(
                "/api/v1/internal/audits",
                json=payload,
                headers=headers,
            )
            assert response.status_code == 202, response.text
            job_id = response.json()["id"]
            with Session(engine) as check_session:
                persisted = check_session.get(AuditJob, UUID(job_id))
                assert persisted is not None
                assert persisted.request_id == response.headers["x-request-id"]
                assert persisted.trace_parent is not None
                assert persisted.trace_parent.startswith("00-")
            assert delivered == [job_id]
            repeated = client.post(
                "/api/v1/internal/audits",
                json=payload,
                headers=headers,
            )
            assert repeated.status_code == 202
            assert repeated.json()["id"] == job_id
            assert delivered == [job_id]
            forbidden = client.get("/api/v1/internal/audits/" + job_id)
            assert forbidden.status_code == 404
            progress = client.get("/api/v1/internal/audits/" + job_id, headers=headers)
            assert progress.status_code == 200
            assert progress.json()["status"] == "queued"
            assert progress.headers["cache-control"] == "no-store, private"
            not_ready = client.get(
                f"/api/v1/internal/audits/{job_id}/report",
                headers=headers,
            )
            assert not_ready.status_code == 409
            cancelled = client.post(
                f"/api/v1/internal/audits/{job_id}/cancel",
                headers=headers,
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"
            cancelled_again = client.post(
                f"/api/v1/internal/audits/{job_id}/cancel",
                headers=headers,
            )
            assert cancelled_again.json()["status"] == "cancelled"
            assert (
                client.get(f"/api/v1/internal/audits/{uuid4()}", headers=headers).status_code == 404
            )

            # A prepared completed report may only be exported after authentication.
            from aiseoonline_api.agents.models import AuditFinding, AuditReport

            issue = AuditFinding(
                finding_id="seo:fixture-html",
                rule_id="title.missing",
                severity="error",
                priority="high",
                affected_url=TARGET,
                summary="<script>alert(1)</script>",
                correction="Add a descriptive page title",
                evidence_quote="=HYPERLINK(1,2)",
                evidence_ref="title:0",
            )
            with Session(engine) as session, session.begin():
                row = session.get(AuditJob, UUID(job_id))
                assert row is not None
                row.report_data = AuditReport(
                    project_id=project_id,
                    requested_url=TARGET,
                    final_url=TARGET,
                    captured_at=datetime.now(UTC),
                    status="partial",
                    findings=[issue],
                    recommendations=[],
                    selected_tools=[],
                    trace=[],
                    uncertainty="One failed step",
                ).model_dump(mode="json")
                row.status = "partial"
            report_response = client.get(
                f"/api/v1/internal/audits/{job_id}/report", headers=headers
            )
            assert report_response.status_code == 200
            assert report_response.headers["cache-control"] == "no-store, private"
            assert report_response.json()["findings"][0]["severity"] == "error"
            html = client.get(
                f"/api/v1/internal/audits/{job_id}/report.html",
                headers=headers,
            )
            assert html.status_code == 200
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html.text
            assert "<script>alert(1)</script>" not in html.text
            assert "default-src 'none'" in html.headers["content-security-policy"]
            csv = client.get(
                f"/api/v1/internal/audits/{job_id}/report.csv",
                headers=headers,
            )
            assert csv.status_code == 200
            assert "'=HYPERLINK(1,2)" in csv.text
            assert "deterministic" in csv.text
            assert client.get(f"/api/v1/internal/audits/{job_id}/report.csv").status_code == 404
    finally:
        with Session(engine) as session, session.begin():
            owner = session.get(User, owner_id)
            if owner:
                session.delete(owner)
        engine.dispose()
