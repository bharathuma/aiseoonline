"""Evidence models for a private, read-only, bounded website audit."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

ToolName = Literal["headings", "canonicals", "structured_data", "social", "links", "rag", "stop"]


class AuditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    owner_id: UUID
    url: str = Field(min_length=12, max_length=2048)
    max_tools: int = Field(default=3, ge=0, le=3)
    max_model_calls: int = Field(default=4, ge=1, le=4)
    max_seconds: int = Field(default=45, ge=5, le=60)
    use_private_rag: bool = False


class ToolChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: ToolName
    reason: str = Field(min_length=5, max_length=180)


class AgentClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: str = Field(min_length=8, max_length=100)
    supporting_quote: str = Field(min_length=3, max_length=180)
    advice: str = Field(min_length=12, max_length=280)


class AgentDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommendations: list[AgentClaim] = Field(max_length=6)
    uncertainty: str = Field(default="", max_length=240)


class AuditFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    finding_id: str
    rule_id: str
    severity: Literal["error", "warning", "info"]
    priority: Literal["high", "medium", "low"]
    affected_url: str
    summary: str
    correction: str
    evidence_quote: str
    evidence_ref: str


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    finding_id: str
    affected_url: str
    priority: Literal["high", "medium", "low"]
    advice: str
    supporting_quote: str
    requires_human_approval: Literal[True] = True
    action_executed: Literal[False] = False


class AuditTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node: str
    outcome: str
    tool: str | None = None


class AuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    requested_url: str
    final_url: str | None
    captured_at: datetime | None
    status: Literal["completed", "partial", "insufficient_evidence"]
    findings: list[AuditFinding]
    recommendations: list[Recommendation]
    selected_tools: list[str]
    trace: list[AuditTrace]
    uncertainty: str
    model: str | None = None
    token_usage: dict[str, int] | None = None
    human_approval_required: Literal[True] = True
    website_changes_performed: Literal[False] = False
    scope: str = "Verified-owner, single-page evidence. Not a sitewide audit."

    @model_validator(mode="after")
    def verify_output_links(self) -> "AuditReport":
        index = {finding.finding_id: finding for finding in self.findings}
        for rec in self.recommendations:
            issue = index.get(rec.finding_id)
            if issue is None or issue.affected_url != rec.affected_url:
                raise ValueError("Recommendation must refer to an actual finding")
        return self
