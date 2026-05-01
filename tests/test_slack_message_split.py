"""_split_for_slack: long outbox text → paragraph-aware multi-part send.

Slack equivalent of v0.4.x's `_split_for_discord`. The outbox row stores
full final_text (up to a 20k sanity cap in finalize); the drainer splits
at paragraph or sentence boundaries and posts each chunk with a `(i/N)`
marker. The cap is `_SLACK_SECTION_LIMIT` (3500) — Block Kit's section
text is hard-capped at 3000 chars; we use 3500 with extra slack for
the splitter to find a clean boundary.
"""
from __future__ import annotations

from donna.adapter.slack_adapter import _SLACK_SECTION_LIMIT, _split_for_slack


def test_short_text_returns_single_part() -> None:
    assert _split_for_slack("hi") == ["hi"]


def test_text_at_limit_returns_single_part() -> None:
    text = "a" * _SLACK_SECTION_LIMIT
    result = _split_for_slack(text)
    assert result == [text]
    assert len(result[0]) == _SLACK_SECTION_LIMIT


def test_splits_on_paragraph_boundary_when_available() -> None:
    para_a = "A" * 2000
    para_b = "B" * 2000
    para_c = "C" * 2000
    text = f"{para_a}\n\n{para_b}\n\n{para_c}"
    parts = _split_for_slack(text)
    assert len(parts) >= 2
    assert all(len(p) <= _SLACK_SECTION_LIMIT for p in parts)
    joined = "\n\n".join(parts)
    assert "A" * 2000 in joined
    assert "B" * 2000 in joined
    assert "C" * 2000 in joined


def test_splits_on_sentence_boundary_when_no_paragraphs() -> None:
    sentence_a = "This is the first sentence. " * 100   # ~2800 chars
    sentence_b = "And another one following it. " * 100  # ~3000 chars
    text = sentence_a + sentence_b
    parts = _split_for_slack(text)
    assert len(parts) >= 2
    assert all(len(p) <= _SLACK_SECTION_LIMIT for p in parts)
    for p in parts[:-1]:
        stripped = p.rstrip()
        assert stripped.endswith((".", "!", "?")), (
            f"part ended without sentence terminator: ...{stripped[-40:]!r}"
        )


def test_splits_hard_when_no_boundary_at_all() -> None:
    """No paragraph, no sentence terminator, no newline — the splitter
    still produces valid chunks ≤ limit, just with less graceful breaks."""
    text = "a" * (_SLACK_SECTION_LIMIT * 3 + 100)
    parts = _split_for_slack(text)
    assert all(len(p) <= _SLACK_SECTION_LIMIT for p in parts)
    assert "".join(parts) == text


def test_splits_large_grounded_answer_shape() -> None:
    """Shape close to live grounded output: prose + citations + footer."""
    claim = "Huck says he can't stand civilization [#chk_1]. "
    body = claim * 80  # ~4000 chars
    footer = "\n\n_✅ validated · sources: Huck Finn_"
    text = body + footer
    parts = _split_for_slack(text)
    assert len(parts) >= 2
    assert all(len(p) <= _SLACK_SECTION_LIMIT for p in parts)
    assert "✅ validated" in parts[-1]


def test_splits_debate_transcript_shape() -> None:
    """Debate renders as markdown headers per turn — `### {scope} — round N`.
    The splitter prefers paragraph boundaries between turns."""
    turns = "\n\n".join(
        f"### author_{who} — round {r}\n" + ("turn content " * 250)
        for who in ("twain", "lewis") for r in (1, 2, 3)
    )
    parts = _split_for_slack(turns)
    assert len(parts) >= 3
    assert all(len(p) <= _SLACK_SECTION_LIMIT for p in parts)


def test_splitter_joins_back_to_original_content() -> None:
    """Content preservation: rejoining parts reproduces a text that contains
    every original character. Catches silent data loss."""
    text = "First para.\n\n" + ("Filler sentence. " * 400) + "\n\nLast para."
    parts = _split_for_slack(text)
    joined = "\n\n".join(parts)
    assert joined.startswith("First para.")
    assert joined.rstrip().endswith("Last para.")
    assert joined.count("Filler sentence.") == 400
