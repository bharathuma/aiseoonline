"""Immutable, serializable SEO findings backed by evidence from page snapshots."""

from dataclasses import asdict, dataclass
from typing import Literal

from aiseoonline_api.crawler.html import Evidence

Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True, slots=True)
class FindingEvidence:
    reference: Evidence
    observed: str


@dataclass(frozen=True, slots=True)
class SeoFinding:
    rule_id: str
    severity: Severity
    url: str
    summary: str
    explanation: str
    recommendation: str
    evidence: tuple[FindingEvidence, ...]

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("A finding must include evidence")

    def to_dict(self) -> dict[str, object]:
        """JSON-safe API payload; dates and untrusted HTML are not serialized here."""
        return asdict(self)

    def to_storage(self) -> dict[str, object]:
        """Values compatible with the initial SQLAlchemy SeoFinding columns."""
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": {
                "url": self.url,
                "explanation": self.explanation,
                "recommendation": self.recommendation,
                "references": [asdict(item) for item in self.evidence],
            },
        }


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    pages_analyzed: int
    duplicate_snapshots: int
    findings: tuple[SeoFinding, ...]
    engine_version: str = "1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
