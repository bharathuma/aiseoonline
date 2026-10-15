"""Bounded HTML SEO evidence extraction. Never evaluates scripts or page instructions."""

import codecs
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .urls import InvalidPage


@dataclass(frozen=True)
class Evidence:
    source_url: str
    element: str
    ordinal: int


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    evidence: Evidence


@dataclass(frozen=True)
class Link:
    href: str
    text: str
    evidence: Evidence


@dataclass(frozen=True)
class MetaTag:
    name: str
    content: str
    evidence: Evidence


@dataclass(frozen=True)
class StructuredData:
    json_text: str
    evidence: Evidence


@dataclass(frozen=True)
class TitleTag:
    text: str
    evidence: Evidence


@dataclass(frozen=True)
class CanonicalTag:
    href: str
    evidence: Evidence


@dataclass(frozen=True)
class ParsedHtml:
    title: str | None
    title_evidence: Evidence | None
    meta: tuple[MetaTag, ...]
    headings: tuple[Heading, ...]
    canonical: tuple[str, ...]
    links: tuple[Link, ...]
    robots: tuple[str, ...]
    structured_data: tuple[StructuredData, ...]
    encoding_repaired: bool
    titles: tuple[TitleTag, ...] = ()
    canonical_tags: tuple[CanonicalTag, ...] = ()


def _clean(text: str, *, max_len: int = 4096) -> str:
    return " ".join(text.split())[:max_len]


class _Extractor(HTMLParser):
    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.title: str | None = None
        self.title_evidence: Evidence | None = None
        self.titles: list[TitleTag] = []
        self.canonical_tags: list[CanonicalTag] = []
        self.meta: list[MetaTag] = []
        self.headings: list[Heading] = []
        self.canonical: list[str] = []
        self.links: list[Link] = []
        self.robots: list[str] = []
        self.structured_data: list[StructuredData] = []
        self._tag: str | None = None
        self._buffer: list[str] = []
        self._active_evidence: Evidence | None = None
        self._active_link: str | None = None
        self._ordinals: dict[str, int] = {}
        self._max_fragment = 8192
        self._characters = 0

    def _evidence(self, tag: str) -> Evidence:
        ordinal = self._ordinals.get(tag, 0) + 1
        self._ordinals[tag] = ordinal
        return Evidence(self.source_url, tag, ordinal)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): (value or "")[:4096] for key, value in attrs[:60]}
        if tag == "meta" and len(self.meta) < 120:
            name = _clean(attrs_map.get("name") or attrs_map.get("property") or "", max_len=100)
            content = _clean(attrs_map.get("content", ""))
            if name:
                self.meta.append(MetaTag(name, content, self._evidence("meta")))
                if name.lower() in ("robots", "googlebot", "bingbot"):
                    self.robots.extend(
                        part.strip().lower() for part in content.split(",")[:40] if part.strip()
                    )
        if tag == "link" and "canonical" in attrs_map.get("rel", "").lower().split():
            if len(self.canonical_tags) < 10:
                href = _clean(attrs_map.get("href", ""))
                self.canonical_tags.append(
                    CanonicalTag(href, self._evidence("link[rel=canonical]"))
                )
                if href:
                    self.canonical.append(href)
        script_type = attrs_map.get("type", "").lower().split(";", 1)[0].strip()
        if tag == "script" and script_type == "application/ld+json":
            if len(self.structured_data) < 20:
                self._tag, self._buffer = "script", []
                self._active_evidence = self._evidence("script[type=application/ld+json]")
            return
        if tag == "title" and len(self.titles) < 10:
            self._tag, self._buffer = "title", []
            self._active_evidence = self._evidence("title")
        elif len(tag) == 2 and tag[0] == "h" and tag[1] in "123456" and len(self.headings) < 100:
            self._tag, self._buffer = tag, []
            self._active_evidence = self._evidence(tag)
        elif tag == "a" and len(self.links) < 500 and attrs_map.get("href"):
            href = attrs_map["href"]
            try:
                absolute = urljoin(self.source_url, href)
                if urlsplit(absolute).scheme.lower() not in ("http", "https"):
                    return
            except ValueError:
                return
            self._tag, self._buffer = "a", []
            self._active_evidence = self._evidence("a")
            self._active_link = _clean(absolute)

    def handle_data(self, data: str) -> None:
        if self._tag is not None and self._characters < self._max_fragment:
            clipped = data[: self._max_fragment - self._characters]
            self._buffer.append(clipped)
            self._characters += len(clipped)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._tag or self._active_evidence is None:
            return
        text = _clean("".join(self._buffer))
        evidence = self._active_evidence
        if tag == "title":
            self.titles.append(TitleTag(text, evidence))
            if self.title_evidence is None:
                self.title = text or None
                self.title_evidence = evidence
        elif tag == "script":
            self.structured_data.append(StructuredData("".join(self._buffer)[:8192], evidence))
        elif tag == "a" and self._active_link:
            self.links.append(Link(self._active_link, text[:500], evidence))
        elif tag.startswith("h"):
            self.headings.append(Heading(int(tag[1]), text[:500], evidence))
        self._tag, self._buffer, self._active_evidence, self._active_link = None, [], None, None
        self._characters = 0


def parse_html(body: bytes, source_url: str, charset: str = "utf-8") -> ParsedHtml:
    """Decode with replacement reporting and parse only bounded fields."""
    try:
        codecs.lookup(charset)
    except (LookupError, TypeError, ValueError):
        charset = "utf-8"
    text = body.decode(charset, errors="replace")
    repaired = "�" in text
    parser = _Extractor(source_url)
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, AssertionError) as exc:
        raise InvalidPage("HTML parser rejected the document") from exc
    return ParsedHtml(
        title=parser.title,
        title_evidence=parser.title_evidence,
        meta=tuple(parser.meta),
        headings=tuple(parser.headings),
        canonical=tuple(parser.canonical),
        links=tuple(parser.links),
        robots=tuple(parser.robots),
        structured_data=tuple(parser.structured_data),
        encoding_repaired=repaired,
        titles=tuple(parser.titles),
        canonical_tags=tuple(parser.canonical_tags),
    )
