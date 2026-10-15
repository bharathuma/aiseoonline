"""Unit tests of private audit budget, authentication, safe output and schema."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aiseoonline_api.agents.execution import (
    _TERMINAL, development_access, estimated_allocation,
)
from aiseoonline_api.agents.models import AuditFinding, AuditReport, Recommendation
from aiseoonline_api.agents.routes import _safe_csv
from aiseoonline_api.config import Settings
from aiseoonline_api.main import create_app


def fixture_settings(**kwargs):
    return Settings(
        _env_file=None, environment="test",
        **kwargs,
    )


def test_private_route_is_not_enabled_without_valid_development_token() -> None:
    settings = fixture_settings()
    with TestClient(create_app(settings)) as client:
        reply = client.post(
            "/api/v1/internal/audits",
            json={"project_id": str(uuid4()), "url": "https://example.org/page"},
            headers={"Idempotency-Key": "private-123456"},
        )
    assert reply.status_code == 404
    assert "audit" not in reply.text.lower()


def test_public_production_cannot_enable_audit_routes() -> None:
    with pytest.raises(ValidationError, match="cannot be enabled in production"):
        Settings(
            _env_file=None, environment="production",
            database_url="postgresql+psycopg://user:pass@localhost/test",
            redis_url="redis://localhost:6379/0",
            audit_jobs_enabled=True,
            audit_dev_token="x" * 48,
            audit_dev_owner_id=uuid4(),
        )


def test_live_budget_requires_prices_and_usable_token_limits() -> None:
    settings = fixture_settings(
        openai_api_key="fixture-only",
        llm_input_usd_per_million=Decimal("1"),
        llm_output_usd_per_million=Decimal("2"),
    )
    estimate = estimated_allocation(settings)
    assert estimate is not None and estimate > 0
    assert estimate <= int(settings.audit_request_usd_cap * 1000000)
    assert estimated_allocation(settings.model_copy(
        update={"openai_api_key": None}
    )) is None
    assert estimated_allocation(settings.model_copy(
        update={"llm_max_output_tokens": 100}
    )) is None


@pytest.mark.parametrize("text", [
    "=SUM(A1:B5)", "-900+2", "+cmd", "@hyperlink", "    =2+2", "\t+2",
])
def test_csv_export_prefixes_spreadsheet_formulas(text: str) -> None:
    assert _safe_csv(text).startswith("'")


def test_csv_export_preserves_ordinary_evidence() -> None:
    assert _safe_csv("missing canonical declaration") == "missing canonical declaration"


def test_report_schema_rejects_fabricated_recommendation_links() -> None:
    finding = AuditFinding(
        finding_id="seo:fixture1", rule_id="title.missing", severity="error",
        priority="high", affected_url="https://example.org/",
        summary="Missing title", correction="Add a descriptive title",
        evidence_quote="title element missing", evidence_ref="title:0",
    )
    with pytest.raises(ValidationError):
        AuditReport(
            project_id=uuid4(), requested_url="https://example.org/",
            final_url="https://example.org/", captured_at=datetime.now(UTC),
            status="completed", findings=[finding],
            recommendations=[
                Recommendation(
                    finding_id="seo:unknown", affected_url="https://example.org/",
                    priority="high", advice="Rewrite the page title.",
                    supporting_quote="title element missing",
                )
            ],
            selected_tools=[], trace=[], uncertainty="",
        )


def test_job_terminal_states_include_cancelled_and_timeout() -> None:
    assert {"cancelled", "timed_out", "partial", "completed"} <= _TERMINAL
