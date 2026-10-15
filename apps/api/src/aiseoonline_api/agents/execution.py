"""Durable private audit lifecycle. All transitions are PostgreSQL-scoped and fail closed."""

import hmac
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import UUID, uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict
from redis import Redis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aiseoonline_api.agents.adapters import project_authorizer
from aiseoonline_api.agents.models import AuditReport, AuditRequest
from aiseoonline_api.config import Settings
from aiseoonline_api.db.models import AuditJob, SeoFinding

_TERMINAL = frozenset(
    {
        "completed",
        "partial",
        "insufficient_evidence",
        "cancelled",
        "failed",
        "timed_out",
    }
)
_STEPS = {
    "queued": 0,
    "authorize": 8,
    "collect": 20,
    "checks": 40,
    "select": 55,
    "tool": 65,
    "analyze": 78,
    "finish": 90,
}

# The first two arguments represent a job count and a budget of micro USD.
_BUDGET_LUA = """
local count=tonumber(redis.call('GET', KEYS[1]) or '0')
local spent=tonumber(redis.call('GET', KEYS[2]) or '0')
if count>=tonumber(ARGV[1]) then return -1 end
if spent+tonumber(ARGV[2])>tonumber(ARGV[3]) then return -2 end
redis.call('INCR', KEYS[1])
if count==0 then redis.call('EXPIRE', KEYS[1], 90000) end
redis.call('INCRBY', KEYS[2], ARGV[2])
if spent==0 then redis.call('EXPIRE', KEYS[2], 90000) end
return 1
"""


class JobUnavailable(PermissionError):
    """Unknown job and unauthorized job have identical behavior."""


class JobConflict(ValueError):
    pass


class JobCancelled(Exception):
    pass


class JobView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    status: str
    progress_step: str
    progress_percent: int
    attempts: int
    cancel_requested: bool
    created_at: datetime
    finished_at: datetime | None
    error_code: str | None
    report_ready: bool


def view(job: AuditJob) -> JobView:
    return JobView(
        id=job.id,
        status=job.status,
        progress_step=job.progress_step,
        progress_percent=job.progress_percent,
        attempts=job.attempts,
        cancel_requested=job.cancel_requested,
        created_at=job.created_at,
        finished_at=job.finished_at,
        error_code=job.error_message,
        report_ready=job.report_data is not None,
    )


def development_access(request: Request, settings: Settings) -> bool:
    if settings.environment not in ("development", "test") or not settings.audit_jobs_enabled:
        return False
    if request.client is None or request.client.host not in ("127.0.0.1", "::1", "testclient"):
        return False
    secret = settings.audit_dev_token
    incoming = request.headers.get("x-dev-audit-token", "")
    if secret is None or not incoming.isascii() or not 32 <= len(incoming) <= 256:
        return False
    return hmac.compare_digest(secret.get_secret_value(), incoming)


def authorized_job(session: Session, job_id: UUID, owner_id: UUID) -> AuditJob:
    job = session.scalar(
        select(AuditJob).where(AuditJob.id == job_id, AuditJob.owner_id == owner_id)
    )
    if job is None or job.project_id is None:
        raise JobUnavailable("Audit job unavailable")
    # Recheck current project access on every read, export and cancellation.
    request = AuditRequest(
        project_id=job.project_id,
        owner_id=owner_id,
        url=job.requested_url or "",
    )
    project_authorizer(session)(request)
    return job


def estimated_allocation(settings: Settings) -> int | None:
    input_rate, output_rate = (
        settings.llm_input_usd_per_million,
        (settings.llm_output_usd_per_million),
    )
    if input_rate is None or output_rate is None or settings.openai_api_key is None:
        return None
    if settings.llm_max_input_tokens < 4096 or settings.llm_max_output_tokens < 440:
        return None
    # Reserve the worst allowed tokens across four calls and all provider retries.
    dollars = (
        (input_rate * settings.llm_max_input_tokens + output_rate * settings.llm_max_output_tokens)
        * 4
        * 3
        * (settings.llm_max_retries + 1)
        / Decimal(1000000)
    )
    micro = int((dollars * 1000000).to_integral_value(rounding=ROUND_CEILING))
    cap = int(settings.audit_request_usd_cap * 1000000)
    return micro if 0 < micro <= cap else None


def reserve_daily_budget(settings: Settings, allocation: int) -> int:
    day = datetime.now(UTC).strftime("%Y%m%d")
    with Redis.from_url(
        settings.require_redis_url(), socket_timeout=1, socket_connect_timeout=1
    ) as redis:
        result = redis.eval(
            _BUDGET_LUA,
            2,
            f"audit:count:{day}",
            f"audit:budget:{day}",
            settings.audit_daily_job_cap,
            allocation,
            int(settings.audit_daily_usd_cap * 1000000),
        )
    return int(result)


def create_job(
    session: Session,
    *,
    request: AuditRequest,
    key: str,
) -> tuple[AuditJob, bool]:
    """Atomic idempotent creation, with trusted owner authorization before enqueue."""
    if (
        not 8 <= len(key) <= 96
        or not key.isascii()
        or not all(char.isalnum() or char in "_-." for char in key)
    ):
        raise ValueError("Idempotency key must be 8–96 safe ASCII characters")
    project_authorizer(session)(request)
    url = request.url
    old = session.scalar(
        select(AuditJob).where(
            AuditJob.project_id == request.project_id,
            AuditJob.idempotency_key == key,
        )
    )
    if old is not None:
        if old.owner_id != request.owner_id or old.request_data != request.model_dump(mode="json"):
            raise JobConflict("Idempotency key is already bound to another request")
        return old, False
    identifier = uuid4()
    values = {
        "id": identifier,
        "project_id": request.project_id,
        "owner_id": request.owner_id,
        "requested_url": url,
        "idempotency_key": key,
        "request_data": request.model_dump(mode="json"),
        "status": "queued",
        "progress_step": "queued",
        "progress_percent": 0,
        "attempts": 0,
        "cancel_requested": False,
    }
    row_id = session.scalar(
        insert(AuditJob)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_audit_project_idempotency")
        .returning(AuditJob.id)
    )
    if row_id is None:
        session.expire_all()
        existing = session.scalar(
            select(AuditJob).where(
                AuditJob.project_id == request.project_id,
                AuditJob.idempotency_key == key,
            )
        )
        if (
            existing is None
            or existing.owner_id != request.owner_id
            or (existing.request_data != request.model_dump(mode="json"))
        ):
            raise JobConflict("Idempotency key conflict")
        return existing, False
    created = session.get(AuditJob, row_id)
    assert created is not None
    return created, True


def cancel_job(session: Session, job_id: UUID, owner_id: UUID) -> AuditJob:
    authorized_job(session, job_id, owner_id)
    job = session.scalar(select(AuditJob).where(AuditJob.id == job_id).with_for_update())
    assert job is not None
    if job.status in _TERMINAL:
        return job
    job.cancel_requested = True
    if job.status == "queued":
        job.status, job.progress_step = "cancelled", "cancelled"
        job.finished_at = datetime.now(UTC)
    else:
        job.progress_step = "cancelling"
    session.flush()
    return job


def claim_job(session: Session, job_id: UUID) -> tuple[AuditRequest, int] | None:
    job = session.scalar(select(AuditJob).where(AuditJob.id == job_id).with_for_update())
    if job is None or job.status in _TERMINAL:
        return None
    now = datetime.now(UTC)
    if job.cancel_requested:
        job.status, job.progress_step = "cancelled", "cancelled"
        job.finished_at = now
        session.flush()
        return None
    if job.status == "running" and job.lease_expires_at and job.lease_expires_at > now:
        return None
    if job.attempts >= 3:
        job.status, job.progress_step = "failed", "failed"
        job.error_message, job.finished_at = "attempt_limit", now
        session.flush()
        return None
    if job.started_at and (now - job.started_at).total_seconds() >= (job.request_data or {}).get(
        "max_seconds", 45
    ):
        job.status, job.progress_step = "timed_out", "timed_out"
        job.error_message, job.finished_at = "audit_deadline", now
        session.flush()
        return None
    request = AuditRequest.model_validate(job.request_data)
    # Re-verify even after stale lease recovery, before any network/model calls.
    try:
        project_authorizer(session)(request)
    except PermissionError:
        job.status, job.progress_step = "failed", "failed"
        job.error_message, job.finished_at = "project_unverified", now
        session.flush()
        return None
    job.status, job.progress_step = "running", "authorize"
    job.progress_percent = max(job.progress_percent, 5)
    job.attempts += 1
    job.started_at = job.started_at or now
    job.lease_expires_at = now + timedelta(seconds=20)
    session.flush()
    return request, job.attempts


def touch_job(session: Session, job_id: UUID, attempt: int, *, step: str | None = None) -> bool:
    job = session.scalar(select(AuditJob).where(AuditJob.id == job_id).with_for_update())
    if job is None or job.status != "running" or job.attempts != attempt or job.cancel_requested:
        return False
    job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=20)
    if step:
        job.progress_step = step
        job.progress_percent = max(job.progress_percent, _STEPS.get(step, 5))
    session.flush()
    return True


def complete_job(
    session: Session,
    job_id: UUID,
    attempt: int,
    *,
    report: AuditReport | None,
    outcome: str = "completed",
) -> bool:
    job = session.scalar(select(AuditJob).where(AuditJob.id == job_id).with_for_update())
    if job is None or job.attempts != attempt or job.status != "running":
        return False
    if job.cancel_requested:
        outcome, report = "cancelled", None
    if report is not None:
        outcome = report.status
        job.report_data = report.model_dump(mode="json")
        # Findings are always deterministic; agent recommendations remain separate JSON.
        for issue in report.findings:
            session.add(
                SeoFinding(
                    audit_job_id=job.id,
                    rule_id=issue.rule_id,
                    finding_key=issue.finding_id,
                    severity=issue.severity,
                    summary=issue.summary,
                    affected_url=issue.affected_url,
                    correction=issue.correction,
                    evidence_ref=issue.evidence_ref,
                    evidence={"observed": issue.evidence_quote, "kind": "deterministic"},
                )
            )
    job.status = outcome
    job.progress_step = outcome
    job.progress_percent = 100 if report is not None else job.progress_percent
    job.error_message = (
        None
        if report is not None
        else ("audit_deadline" if outcome == "timed_out" else "audit_unavailable")
    )
    job.finished_at = datetime.now(UTC)
    job.lease_expires_at = None
    session.flush()
    return True


def overdue_jobs(session: Session, *, limit: int = 20) -> list[UUID]:
    """Requeue missing Redis delivery and crashed workers via periodic scheduler."""
    now = datetime.now(UTC)
    rows = session.scalars(
        select(AuditJob)
        .where(
            (AuditJob.status == "queued")
            | ((AuditJob.status == "running") & (AuditJob.lease_expires_at < now))
        )
        .order_by(AuditJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    ).all()
    queued: list[UUID] = []
    for job in rows:
        deadline = (job.request_data or {}).get("max_seconds", 45)
        if job.started_at and (now - job.started_at).total_seconds() > deadline:
            job.status, job.progress_step = "timed_out", "timed_out"
            job.error_message, job.finished_at = "audit_deadline", now
        elif job.cancel_requested:
            job.status, job.progress_step = "cancelled", "cancelled"
            job.finished_at = now
        elif job.attempts >= 3:
            job.status, job.progress_step = "failed", "failed"
            job.error_message, job.finished_at = "attempt_limit", now
        else:
            job.status, job.progress_step = "queued", "queued"
            job.lease_expires_at = None
            queued.append(job.id)
    session.flush()
    return queued
