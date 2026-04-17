"""Paragraph-aware chunker. Target ~500 tokens with ~80 tokens overlap."""
from __future__ import annotations

from dataclasses import dataclass

CHARS_PER_TOKEN = 4  # rough


@dataclass
class TextChunk:
    index: int
    content: str
    token_count: int


def chunk_text(
    text: str, *, target_tokens: int = 500, overlap_tokens: int = 80
) -> list[TextChunk]:
    target_chars = target_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    # Split on blank lines (paragraphs)
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paras:
        return []

    chunks: list[TextChunk] = []
    buf = ""
    idx = 0

    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) + len(p) + 2 <= target_chars:
            buf = buf + "\n\n" + p
        else:
            chunks.append(TextChunk(index=idx, content=buf, token_count=len(buf)//CHARS_PER_TOKEN))
            idx += 1
            # Overlap: take the tail of the prior chunk
            tail = buf[-overlap_chars:] if overlap_chars > 0 else ""
            buf = (tail + "\n\n" + p).strip()

    if buf:
        chunks.append(TextChunk(index=idx, content=buf, token_count=len(buf)//CHARS_PER_TOKEN))

    return chunks
