"""Pure section-aware chunking and duplicate-safe deterministic content hashes."""

import hashlib
import re
from dataclasses import dataclass

from aiseoonline_api.crawler.content import ContentSection

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading: str | None
    text: str
    content_hash: str


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunks_from_sections(
    sections: tuple[ContentSection, ...],
    *,
    size: int = 750,
    overlap: int = 90,
    max_chunks: int = 24,
) -> tuple[Chunk, ...]:
    if not (200 <= size <= 2000 and 0 <= overlap < size // 2):
        raise ValueError("Invalid chunk size or overlap")
    if not 1 <= max_chunks <= 100:
        raise ValueError("Invalid maximum chunk budget")
    chunks: list[Chunk] = []
    for section in sections:
        text = _SPACE.sub(" ", section.text).strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            if len(chunks) >= max_chunks:
                raise ValueError("Document exceeds ingestion chunk budget")
            end = min(len(text), start + size)
            if end < len(text):
                boundary = text.rfind(" ", start + size // 2, end)
                if boundary > start:
                    end = boundary
            value = text[start:end].strip()
            if value:
                chunks.append(Chunk(
                    ordinal=len(chunks), heading=section.heading,
                    text=value, content_hash=hash_text(value),
                ))
            if end >= len(text):
                break
            start = max(start + 1, end - overlap)
    if not chunks:
        raise ValueError("No indexable text in page")
    return tuple(chunks)
