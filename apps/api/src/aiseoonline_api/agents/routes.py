"""Local-only authorized audit lifecycle and read-only evidence exports."""

import asyncio
import csv
import io
from html import escape
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from aiseoonline_api.agents.execution import (
    JobConflict,
    JobUnavailable,
    JobView,
    authorized_job,
    cancel_job,
    create_job,
    development_access,
    estimated_allocation,
    reserve_daily_budget,
    view,
)
from aiseoonline_api.agents.models import AuditReport, AuditRequest
from aiseoonline_api.config import Settings
from aiseoonline_api.errors import error_response
from aiseoonline_api.jobs import create_celery_app
from aiseoonline_api.rag.store import RagAccessDenied

router = APIRouter(tags=["Internal development audit jobs"])


class CreateAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    url: str = Field(min_length=12, max_length=2048)


def _access(request: Request) -> bool:
    return development_access(request, request.app.state.settings)


def _engine(request: Request):
    return request.app.state.database_engine


@router.post("/internal/audits", response_model=JobView, status_code=202)
async def enqueue(
    request: Request,
    body: CreateAudit,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
) -> JobView | JSONResponse:
    response.headers["Cache-Control"] = "no-store, private"
    if not _access(request):
        return error_response(request, 404, "not_found", "Resource unavailable.")
    settings: Settings = request.app.state.settings
    owner = settings.audit_dev_owner_id
    if owner is None or _engine(request) is None:
        return error_response(request, 503, "service_unavailable", "Audits unavailable.")
    request_data = AuditRequest(
        project_id=body.project_id,
        owner_id=owner,
        url=body.url,
        max_tools=2,
        max_model_calls=3,
        max_seconds=45,
        use_private_rag=False,
    )
    allocation = estimated_allocation(settings)
    if allocation is None:
        return error_response(
            request,
            503,
            "audit_budget_unavailable",
            "The audit provider and cost limits are not configured.",
        )
    try:
        with Session(_engine(request)) as session, session.begin():
            job, created = create_job(session, request=request_data, key=idempotency_key)
            if created:
                remaining = await asyncio.to_thread(reserve_daily_budget, settings, allocation)
                if remaining != 1:
                    raise RuntimeError("audit_budget_reached")
            identifier = job.id
            result = view(job)
    except (RagAccessDenied, JobUnavailable):
        return error_response(request, 404, "not_found", "Project unavailable.")
    except (JobConflict, ValueError):
        return error_response(request, 409, "audit_conflict", "Idempotency key conflict.")
    except RuntimeError as exc:
        if str(exc) == "audit_budget_reached":
            return error_response(
                request,
                429,
                "audit_limit_reached",
                "The daily audit request or spending allocation is exhausted.",
            )
        return error_response(request, 503, "service_unavailable", "Audit queue unavailable.")
    except (RedisError, OSError, TimeoutError):
        return error_response(request, 503, "service_unavailable", "Audit limits unavailable.")
    if created:
        try:
            await asyncio.to_thread(
                create_celery_app(settings).send_task,
                "aiseoonline.audit.execute",
                args=[str(identifier)],
                task_id=str(identifier),
            )
        except Exception:
            # A committed queued job will be retried by the periodic recovery sweep.
            return error_response(
                request,
                503,
                "queue_pending",
                "Audit was recorded but queue dispatch is delayed. Retry with the same key.",
            )
    return result


@router.get("/internal/audits/{job_id}", response_model=JobView)
def status(request: Request, job_id: UUID, response: Response) -> JobView | JSONResponse:
    response.headers["Cache-Control"] = "no-store, private"
    if not _access(request):
        return error_response(request, 404, "not_found", "Resource unavailable.")
    owner = request.app.state.settings.audit_dev_owner_id
    if owner is None or _engine(request) is None:
        return error_response(request, 503, "service_unavailable", "Audits unavailable.")
    try:
        with Session(_engine(request)) as session:
            result = view(authorized_job(session, job_id, owner))
    except (JobUnavailable, RagAccessDenied, ValueError):
        return error_response(request, 404, "not_found", "Audit unavailable.")
    return result


@router.post("/internal/audits/{job_id}/cancel", response_model=JobView)
def cancel(request: Request, job_id: UUID, response: Response) -> JobView | JSONResponse:
    response.headers["Cache-Control"] = "no-store, private"
    if not _access(request):
        return error_response(request, 404, "not_found", "Resource unavailable.")
    owner = request.app.state.settings.audit_dev_owner_id
    if owner is None or _engine(request) is None:
        return error_response(request, 503, "service_unavailable", "Audits unavailable.")
    try:
        with Session(_engine(request)) as session, session.begin():
            result = view(cancel_job(session, job_id, owner))
    except (JobUnavailable, RagAccessDenied, ValueError):
        return error_response(request, 404, "not_found", "Audit unavailable.")
    return result


def _report(request: Request, job_id: UUID) -> AuditReport | JSONResponse:
    if not _access(request):
        return error_response(request, 404, "not_found", "Resource unavailable.")
    owner = request.app.state.settings.audit_dev_owner_id
    if owner is None or _engine(request) is None:
        return error_response(request, 503, "service_unavailable", "Audits unavailable.")
    try:
        with Session(_engine(request)) as session:
            job = authorized_job(session, job_id, owner)
            raw = job.report_data
    except (JobUnavailable, RagAccessDenied, ValueError):
        return error_response(request, 404, "not_found", "Audit unavailable.")
    if raw is None:
        return error_response(
            request,
            409,
            "report_not_ready",
            "The report is not available; check the audit job status.",
        )
    return AuditReport.model_validate(raw)


@router.get("/internal/audits/{job_id}/report", response_model=AuditReport)
def report_json(request: Request, job_id: UUID, response: Response) -> AuditReport | JSONResponse:
    response.headers["Cache-Control"] = "no-store, private"
    return _report(request, job_id)


def _safe_csv(value: str) -> str:
    if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


@router.get("/internal/audits/{job_id}/report.csv")
def report_csv(request: Request, job_id: UUID) -> Response:
    result = _report(request, job_id)
    if isinstance(result, JSONResponse):
        return result
    data = io.StringIO()
    writer = csv.writer(data)
    writer.writerow(
        [
            "kind",
            "severity",
            "affected_url",
            "finding_id",
            "summary_or_advice",
            "evidence",
            "correction",
        ]
    )
    for finding in result.findings:
        writer.writerow(
            [
                _safe_csv(value)
                for value in (
                    "deterministic",
                    finding.severity,
                    finding.affected_url,
                    finding.finding_id,
                    finding.summary,
                    finding.evidence_quote,
                    finding.correction,
                )
            ]
        )
    for advice in result.recommendations:
        writer.writerow(
            [
                _safe_csv(value)
                for value in (
                    "ai_interpretation",
                    advice.priority,
                    advice.affected_url,
                    advice.finding_id,
                    advice.advice,
                    advice.supporting_quote,
                    "Human review required",
                )
            ]
        )
    return Response(
        data.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="audit-{job_id}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/internal/audits/{job_id}/report.html")
def report_html(request: Request, job_id: UUID) -> Response:
    result = _report(request, job_id)
    if isinstance(result, JSONResponse):
        return result
    rows = "".join(
        "<article><h3>"
        + escape(issue.summary)
        + "</h3>"
        + "<p><strong>Severity:</strong> "
        + escape(issue.severity)
        + " <strong>URL:</strong> "
        + escape(issue.affected_url)
        + "</p>"
        + "<p><strong>Observed:</strong> "
        + escape(issue.evidence_quote)
        + "</p>"
        + "<p><strong>Correction:</strong> "
        + escape(issue.correction)
        + "</p></article>"
        for issue in result.findings
    )
    recommendations = "".join(
        "<article><h3>AI interpretation — human approval required</h3>"
        + "<p>"
        + escape(advice.advice)
        + "</p>"
        + "<p>Supporting quote: "
        + escape(advice.supporting_quote)
        + "</p></article>"
        for advice in result.recommendations
    )
    html = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='robots' content='noindex,nofollow'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Private SEO audit</title>"
        "<style>body{font:16px system-ui;max-width:55rem;margin:2rem auto;padding:1rem;"
        "line-height:1.6;color:#182c3a}article{border:1px solid #bccbd3;"
        "padding:1rem;margin:1rem 0;border-radius:.5rem}h1{color:#153849}</style>"
        "</head><body><h1>Private SEO audit</h1><p>Scope: one verified page only. "
        "Search rankings are not guaranteed. No website changes were made.</p>"
        "<h2>Observed technical findings</h2>"
        + (rows or "<p>No findings.</p>")
        + "<h2>AI interpretations (not verified facts)</h2>"
        + (recommendations or "<p>No AI recommendations.</p>")
        + "<p>Uncertainty: "
        + escape(result.uncertainty)
        + "</p></body></html>"
    )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )
