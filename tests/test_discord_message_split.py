"""_split_for_discord: long outbox text → paragraph-aware multi-part send.

Replaces the silent `text[:1500]` truncation in _post_update. The outbox
row now stores full final_text (up to a 20k sanity cap in finalize); the
drainer splits at paragraph or sentence boundaries and posts each chunk
with a `(i/N)` marker.

Known issue from docs/KNOWN_ISSUES.md:
  "1500-char truncation on send_update — long-form summaries get cut
   mid-sentence."

This closes it for the finalize→outbox→post path (the one users actually
complain about). `send_update` tool itself keeps its 1500-char cap
because those are explicit progress pings, not final answers.
"""
from __future__ import annotations

from donna.adapter.discord_adapter import _DISCORD_MSG_LIMIT, _split_for_discord


def test_short_text_returns_single_part() -> None:
    assert _split_for_discord("hi") == ["hi"]


def test_text_at_limit_returns_single_part() -> None:
    text = "a" * _DISCORD_MSG_LIMIT
    result = _split_for_discord(text)
    assert result == [text]
    assert len(result[0]) == _DISCORD_MSG_LIMIT


def test_splits_on_paragraph_boundary_when_available() -> None:
    para_a = "A" * 800
    para_b = "B" * 800
    para_c = "C" * 800
    text = f"{para_a}\n\n{para_b}\n\n{para_c}"
    parts = _split_for_discord(text)
    assert len(parts) >= 2
    # Every part must respect the limit
    assert all(len(p) <= _DISCORD_MSG_LIMIT for p in parts)
    # Content is preserved (allowing for trim of split-boundary whitespace)
    joined = "\n\n".join(parts)
    assert "A" * 800 in joined
    assert "B" * 800 in joined
    assert "C" * 800 in joined


def test_splits_on_sentence_boundary_when_no_paragraphs() -> None:
    sentence_a = "This is the first sentence. " * 40     # ~1120 chars
    sentence_b = "And another one following it. " * 40   # ~1200 chars
    text = sentence_a + sentence_b
    parts = _split_for_discord(text)
    assert len(parts) >= 2
    assert all(len(p) <= _DISCORD_MSG_LIMIT for p in parts)
    # No part ends mid-word if a sentence terminator was available
    for p in parts[:-1]:
        stripped = p.rstrip()
        assert stripped.endswith((".", "!", "?")), (
            f"part ended without sentence terminator: ...{stripped[-40:]!r}"
        )


def test_splits_hard_when_no_boundary_at_all() -> None:
    """No paragraph, no sentence terminator, no newline — the splitter
    still produces valid chunks ≤ limit, just with less graceful breaks."""
    text = "a" * 4500  # three full chunks worth
    parts = _split_for_discord(text)
    assert all(len(p) <= _DISCORD_MSG_LIMIT for p in parts)
    assert "".join(parts) == text


def test_splits_large_grounded_answer_shape() -> None:
    """Shape close to the live smoke-test output: markdown-ish prose with
    citations, a validated badge, and sources line at the end."""
    claim = "Huck says he can't stand civilization [#chk_1]. "
    body = claim * 60  # ~3000 chars
    footer = "\n\n_✅ validated · sources: Huck Finn_"
    text = body + footer
    parts = _split_for_discord(text)
    assert len(parts) >= 2
    assert all(len(p) <= _DISCORD_MSG_LIMIT for p in parts)
    # The footer should land in the LAST chunk (user wants the validator
    # badge visible once the answer ends, not buried mid-stream)
    assert "✅ validated" in parts[-1]


def test_splits_debate_transcript_shape() -> None:
    """Debate renders as markdown headers per turn — `### {scope} — round N`.
    The splitter should prefer paragraph boundaries between turns."""
    turns = "\n\n".join(
        f"### author_{who} — round {r}\n" + ("turn content " * 80)
        for who in ("twain", "lewis") for r in (1, 2, 3)
    )
    parts = _split_for_discord(turns)
    assert len(parts) >= 3
    assert all(len(p) <= _DISCORD_MSG_LIMIT for p in parts)


def test_splitter_joins_back_to_original_content() -> None:
    """Content preservation: rejoining parts reproduces a text that contains
    every original character (possibly with whitespace boundaries collapsed).
    Catches silent data loss in the splitter."""
    text = "First para.\n\n" + ("Filler sentence. " * 150) + "\n\nLast para."
    parts = _split_for_discord(text)
    joined = "\n\n".join(parts)
    # "First para." and "Last para." must survive intact
    assert joined.startswith("First para.")
    assert joined.rstrip().endswith("Last para.")
    # Filler content is preserved too
    assert joined.count("Filler sentence.") == 150
