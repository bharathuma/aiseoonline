"""Bounded page text extraction. Ignore scripts, site chrome and markup directives."""

from dataclasses import dataclass
from html.parser import HTMLParser

_SKIP = frozenset({"script", "style", "noscript", "template", "svg", "nav",
                   "header", "footer", "aside", "form", "button"})
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_BLOCKS = frozenset({"p", "li", "blockquote", "td", "dd", "dt"})
_MAX_TEXT = 24000
_MAX_SECTIONS = 80


@dataclass(frozen=True)
class ContentSection:
    heading: str | None
    text: str


class _SectionExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.in_main = 0
        self.in_body = 0
        self.heading_tag: str | None = None
        self.heading_parts: list[str] = []
        self.heading: str | None = None
        self.parts: list[str] = []
        self.main_heading: str | None = None
        self.main_parts: list[str] = []
        self.sections: list[ContentSection] = []
        self.main_sections: list[ContentSection] = []
        self.used = 0

    def _flush(self, main: bool) -> None:
        parts = self.main_parts if main else self.parts
        heading = self.main_heading if main else self.heading
        output = self.main_sections if main else self.sections
        text = " ".join(" ".join(parts).split())[:_MAX_TEXT]
        if text and len(output) < _MAX_SECTIONS:
            output.append(ContentSection(heading, text))
        parts.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # Ignore attributes entirely: page text is inert data.
        self.tags.append(tag)
        if tag == "body":
            self.in_body += 1
        if tag in ("main", "article"):
            self.in_main += 1
        if any(t in _SKIP for t in self.tags):
            return
        if tag in _HEADINGS:
            self._flush(False)
            if self.in_main:
                self._flush(True)
            self.heading_tag = tag
            self.heading_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_body == 0 or self.used >= _MAX_TEXT:
            return
        if any(t in _SKIP for t in self.tags):
            return
        clean = " ".join(data.split())
        if not clean:
            return
        clean = clean[:_MAX_TEXT - self.used]
        self.used += len(clean)
        if self.heading_tag is not None:
            self.heading_parts.append(clean)
        else:
            self.parts.append(clean)
            if self.in_main:
                self.main_parts.append(clean)

    def handle_endtag(self, tag: str) -> None:
        if tag == self.heading_tag:
            heading = " ".join(" ".join(self.heading_parts).split())[:180] or None
            self.heading = heading
            if self.in_main:
                self.main_heading = heading
            self.heading_tag = None
            self.heading_parts = []
        if tag in _BLOCKS and self.parts:
            self.parts.append(". ")
            if self.in_main and self.main_parts:
                self.main_parts.append(". ")
        if tag == "main" or tag == "article":
            self._flush(True)
            self.in_main = max(0, self.in_main - 1)
        if tag == "body":
            self._flush(False)
            self.in_body = max(0, self.in_body - 1)
        # HTML may be malformed. Pop to the closest tag without executing anything.
        if tag in self.tags:
            idx = len(self.tags) - 1 - self.tags[::-1].index(tag)
            del self.tags[idx:]

    def finish(self) -> tuple[ContentSection, ...]:
        self._flush(False)
        self._flush(True)
        selected = self.main_sections if any(s.text.strip() for s in self.main_sections) else self.sections
        return tuple(selected[:_MAX_SECTIONS])


def extract_sections(html: str) -> tuple[ContentSection, ...]:
    parser = _SectionExtractor()
    parser.feed(html[:250000])
    parser.close()
    return parser.finish()
