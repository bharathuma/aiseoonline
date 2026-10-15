"""Celery worker-side execution with PostgreSQL LangGraph checkpoints and leases."""

import asyncio
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from aiseoonline_api.agents.adapters import project_authorizer
from aiseoonline_api.agents.execution import (
    JobCancelled,
    claim_job,
    complete_job,
    touch_job,
)
from aiseoonline_api.agents.models import AuditReport
from aiseoonline_api.agents.workflow import AuditAgent
from aiseoonline_api.ai_core import LLMProvider, make_openai_provider
from aiseoonline_api.config import Settings
from aiseoonline_api.db.session import create_database_engine
from aiseoonline_api.observability import configure_telemetry, span, trace_from_parent

logger = logging.getLogger("aiseoonline.audit")


async def _execute(
    job_id: UUID,
    *,
    settings: Settings,
    engine: Engine,
    request,
    attempt: int,
    provider: LLMProvider,
    fetch: Callable | None = None,
) -> AuditReport:
    checkpoint_url = settings.require_database_url().replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    async with AsyncPostgresSaver.from_conn_string(checkpoint_url) as saver:
        # setup() is idempotent, but must be run before the first checkpoint.
        await saver.setup()
        with Session(engine) as session:

            def on_step(step: str) -> None:
                with Session(engine) as update_session, update_session.begin():
                    alive = touch_job(update_session, job_id, attempt, step=step)
                if not alive:
                    raise JobCancelled("Cancelled or superseded audit worker")

            agent = AuditAgent(
                authorize=project_authorizer(session),
                llm=provider,
                fetch=fetch,
                on_step=on_step,
            )
            from aiseoonline_api.db.models import AuditJob

            record = session.get(AuditJob, job_id)
            assert record is not None
            with (
                trace_from_parent(
                    record.trace_parent, request_id=record.request_id or "-", job_id=str(job_id)
                ),
                span("audit.job", attempt=attempt),
            ):
                return await agent.run(request, checkpointer=saver, thread_id=f"audit:{job_id}")


def execute_audit_job(
    job_id: UUID,
    *,
    settings: Settings | None = None,
    provider_factory: Callable[[Settings], LLMProvider] | None = None,
    fetch: Callable | None = None,
) -> str:
    """Idempotent worker entry; accepted duplicate tasks never execute concurrently.

    The heartbeat extends the lease while a slow model call is in progress.
    All DB state changes are protected by the claimed attempt number.
    """
    resolved = settings or Settings()
    configure_telemetry(resolved)
    if not resolved.audit_jobs_enabled or resolved.environment == "production":
        return "disabled"
    engine = create_database_engine(resolved)
    try:
        with Session(engine) as session, session.begin():
            claimed = claim_job(session, job_id)
        if claimed is None:
            return "not_claimed"
        request, attempt = claimed
        stop = threading.Event()

        def heartbeat() -> None:
            while not stop.wait(5):
                try:
                    with Session(engine) as session, session.begin():
                        if not touch_job(session, job_id, attempt):
                            break
                except Exception:
                    # A lost DB/heartbeat is not a reason to continue side effects.
                    stop.set()
                    break

        watcher = threading.Thread(target=heartbeat, daemon=True)
        watcher.start()
        outcome = "failed"
        report: AuditReport | None = None
        provider: LLMProvider | None = None
        try:
            provider = (
                provider_factory(resolved) if provider_factory else make_openai_provider(resolved)
            )
            # The original timestamp applies across redelivery and checkpoint recovery.
            with Session(engine) as session:
                from aiseoonline_api.db.models import AuditJob

                record = session.get(AuditJob, job_id)
                assert record is not None and record.started_at is not None
                began = record.started_at
                if began.tzinfo is None:
                    began = began.replace(tzinfo=UTC)
            elapsed = max(0, (datetime.now(UTC) - began).total_seconds())
            remaining = request.max_seconds - elapsed
            if remaining <= 0:
                outcome = "timed_out"
            else:

                async def run() -> AuditReport:
                    async with asyncio.timeout(remaining):
                        return await _execute(
                            job_id,
                            settings=resolved,
                            engine=engine,
                            request=request,
                            attempt=attempt,
                            provider=provider,
                            fetch=fetch,
                        )

                report = asyncio.run(run())
                outcome = report.status
        except TimeoutError:
            outcome = "timed_out"
        except JobCancelled:
            outcome = "cancelled"
        except Exception:
            # Never log credentials, crawling content, provider errors or traces.
            logger.error("Private audit execution failed job_id=%s", job_id)
            outcome = "failed"
        finally:
            stop.set()
            watcher.join(timeout=1)
            if provider is not None and hasattr(provider, "aclose"):
                asyncio.run(provider.aclose())
        with Session(engine) as session, session.begin():
            committed = complete_job(session, job_id, attempt, report=report, outcome=outcome)
        return outcome if committed else "superseded"
    finally:
        engine.dispose()
