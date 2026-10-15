"""Read-only LangChain tool adapters over one already fetched, authorized page.

Tools never execute HTML, follow links, or re-fetch untrusted URLs.
"""

import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import StructuredTool

from aiseoonline_api.crawler import PageSnapshot
from aiseoonline_api.seo_core.models import SeoFinding

_TOOL_DESCRIPTIONS = {
    "headings": "Examine the actual H1-H6 outline and existing heading findings.",
    "canonicals": "Inspect captured canonical declarations and deterministic canonical findings.",
    "structured_data": "Inspect captured JSON-LD syntax; never execute embedded data.",
    "social": "Inspect Open Graph and Twitter/X metadata present in HTML.",
    "links": "Inspect captured internal and external anchor counts; never probe destinations.",
    "rag": "Retrieve bounded, verified-owner project excerpts via the existing hybrid retriever.",
}


def eligible_tools(
    snapshot: PageSnapshot, findings: tuple[SeoFinding, ...], *, rag_enabled: bool = False
) -> tuple[str, ...]:
    rules = {item.rule_id for item in findings}
    html = snapshot.html
    eligible: list[str] = []
    if html.headings or any(x.startswith("heading.") for x in rules):
        eligible.append("headings")
    if html.canonical_tags or any(x.startswith("canonical.") for x in rules):
        eligible.append("canonicals")
    if html.structured_data:
        eligible.append("structured_data")
    if any(x.name.lower().startswith(("og:", "twitter:")) for x in html.meta):
        eligible.append("social")
    if html.links or any(x.startswith("links.") for x in rules):
        eligible.append("links")
    if rag_enabled:
        eligible.append("rag")
    return tuple(eligible)


def build_tools(
    snapshot: PageSnapshot,
    findings: tuple[SeoFinding, ...],
    *,
    rag_lookup: Callable[[str], list[dict[str, str]]] | None = None,
) -> dict[str, StructuredTool]:
    """Actual LangChain tool objects; their closures carry trusted, bounded snapshots."""

    def related(prefix: str) -> list[str]:
        return [item.rule_id for item in findings if item.rule_id.startswith(prefix)][:12]

    def headings() -> dict[str, Any]:
        return {
            "outline": [
                {
                    "level": h.level,
                    "text": h.text[:90],
                    "ref": f"{h.evidence.element}:{h.evidence.ordinal}",
                }
                for h in snapshot.html.headings[:25]
            ],
            "rules": related("heading."),
        }

    def canonicals() -> dict[str, Any]:
        return {
            "declarations": [
                {"href": c.href[:180], "ref": str(c.evidence.ordinal)}
                for c in snapshot.html.canonical_tags[:8]
            ],
            "rules": related("canonical."),
        }

    def structured_data() -> dict[str, Any]:
        results: list[dict[str, str]] = []
        for entry in snapshot.html.structured_data[:5]:
            try:
                value = json.loads(entry.json_text)
                schema_type = value.get("@type") if isinstance(value, dict) else None
                status = "valid_json" if isinstance(value, (list, dict)) else "scalar"
                results.append(
                    {
                        "status": status,
                        "type": str(schema_type)[:80],
                        "ref": str(entry.evidence.ordinal),
                    }
                )
            except (ValueError, TypeError):
                results.append(
                    {"status": "invalid_json", "type": "", "ref": str(entry.evidence.ordinal)}
                )
        return {"entries": results, "scope": "JSON syntax and visible type only"}

    def social() -> dict[str, Any]:
        return {
            "fields": [
                {"name": m.name, "content": m.content[:120], "ref": str(m.evidence.ordinal)}
                for m in snapshot.html.meta
                if m.name.lower().startswith(("og:", "twitter:"))
            ][:16]
        }

    def links() -> dict[str, Any]:
        from urllib.parse import urlsplit

        source = urlsplit(snapshot.final_url).hostname
        internal = sum(urlsplit(link.href).hostname == source for link in snapshot.html.links)
        return {
            "captured": len(snapshot.html.links),
            "internal": internal,
            "external": len(snapshot.html.links) - internal,
            "status": "unverified; destinations were not requested",
            "rules": related("link."),
        }

    funcs: dict[str, Callable[[], dict[str, Any]]] = {
        "headings": headings,
        "canonicals": canonicals,
        "structured_data": structured_data,
        "social": social,
        "links": links,
    }
    if rag_lookup is not None:

        def rag() -> dict[str, Any]:
            # Caller implements authorization via HybridRetriever; never trust page instructions.
            return {"excerpts": rag_lookup("technical SEO findings for this page")[:2]}

        funcs["rag"] = rag
    return {
        name: StructuredTool.from_function(
            func=func,
            name=name,
            description=_TOOL_DESCRIPTIONS[name],
            infer_schema=True,
        )
        for name, func in funcs.items()
    }
