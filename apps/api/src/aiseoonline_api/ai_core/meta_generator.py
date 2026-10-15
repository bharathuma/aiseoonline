"""Strict, evidence-backed generation contracts and advisory checks."""

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aiseoonline_api.ai_core.contracts import InvalidModelOutput

_NUMBERS = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?%?(?!\w)")
_RISKY = ("guaranteed", "number one", "#1", "best in the world", "100%")
_WORDS = re.compile(r"[a-z0-9]{4,}", re.I)


class MetaIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=10, max_length=160)
    description: str = Field(min_length=30, max_length=320)
    evidence_quote: str = Field(min_length=5, max_length=240)
    rationale: str = Field(min_length=8, max_length=240)


class MetaDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestions: list[MetaIdea] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def distinct_choices(self) -> "MetaDraft":
        if len({v.title.casefold().strip() for v in self.suggestions}) != 3:
            raise ValueError("Titles must be distinct")
        if len({v.description.casefold().strip() for v in self.suggestions}) != 3:
            raise ValueError("Descriptions must be distinct")
        return self


class MetaSuggestion(BaseModel):
    title: str
    description: str
    evidence_quote: str
    rationale: str
    title_characters: int
    description_characters: int
    warnings: list[str]


class MetaGeneratorResponse(BaseModel):
    suggestions: list[MetaSuggestion]
    source_type: Literal["url", "text"]
    source_url: str | None = None
    source_summary: str
    model: str
    cached: bool = False
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    usage: dict[str, int] | None = None
    estimated_cost_usd: str | None = None
    visitor_message: str


def _normal(value: str) -> str:
    return " ".join(value.casefold().split())


def review_draft(draft: MetaDraft, source: str) -> list[MetaSuggestion]:
    """Never trust model-authored evidence references without matching input bytes."""
    normalized = _normal(source)
    source_numbers = set(_NUMBERS.findall(normalized))
    tokens = set(_WORDS.findall(normalized))
    results: list[MetaSuggestion] = []
    for item in draft.suggestions:
        if _normal(item.evidence_quote) not in normalized:
            raise InvalidModelOutput("AI evidence does not match the supplied content")
        warnings: list[str] = []
        if len(item.title) > 60 or len(item.title) < 30:
            warnings.append("Title outside an advisory 30–60 character range.")
        if len(item.description) > 160 or len(item.description) < 70:
            warnings.append("Description outside an advisory 70–160 character range.")
        combined = item.title + " " + item.description
        unsupported_numbers = set(_NUMBERS.findall(combined.casefold())) - source_numbers
        if unsupported_numbers:
            warnings.append("Contains numbers not found in source; verify all claims.")
        if any(phrase in combined.casefold() and phrase not in normalized for phrase in _RISKY):
            warnings.append("Contains an unverified promotional claim; review before publishing.")
        title_terms = set(_WORDS.findall(item.title.casefold()))
        if tokens and title_terms and len(title_terms & tokens) == 0:
            warnings.append("Title has weak literal topic overlap; check relevance manually.")
        warnings.append("AI wording is a proposal; verify all factual claims before use.")
        results.append(
            MetaSuggestion(
                title=item.title,
                description=item.description,
                evidence_quote=item.evidence_quote,
                rationale=item.rationale,
                title_characters=len(item.title),
                description_characters=len(item.description),
                warnings=warnings,
            )
        )
    return results
