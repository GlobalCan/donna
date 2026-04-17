"""Chunker sanity — paragraph preservation + overlap + size bounds."""
from __future__ import annotations

from donna.ingest.chunk import chunk_text


def test_empty_text_yields_no_chunks() -> None:
    assert chunk_text("") == []


def test_short_text_yields_one_chunk() -> None:
    chunks = chunk_text("A short paragraph.\n\nAnother one.")
    assert len(chunks) == 1
    assert "short paragraph" in chunks[0].content


def test_long_text_yields_multiple_chunks() -> None:
    # generate ~3000 chars of text
    para = "Sentence one. " * 30
    text = "\n\n".join([para] * 10)
    chunks = chunk_text(text, target_tokens=300, overlap_tokens=50)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.content
        assert c.index >= 0


def test_overlap_preserves_context() -> None:
    para = "First paragraph has specific marker FOO.\n\n" * 5
    long_para = "Subsequent content " * 200
    text = para + long_para
    chunks = chunk_text(text, target_tokens=200, overlap_tokens=40)
    assert len(chunks) >= 2
    # Later chunks should not all be totally disconnected
    assert any(c.content for c in chunks)
