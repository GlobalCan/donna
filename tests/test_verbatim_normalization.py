"""Smart-quote + Unicode normalization in _verbatim_in.

The quoted_span validator is strict on CONTENT (no paraphrase) but must
absorb common LLM rendering variations that are invisible to humans:

- Curly vs straight apostrophes: ' vs ' / '
- Curly vs straight double quotes: " vs " / "
- En dash / em dash / non-breaking hyphen → ASCII -
- Horizontal ellipsis character (…) vs three periods (...)
- Unicode NFC normalization (composed vs decomposed forms)

Real paraphrases still fail — this is a content-preserving strictness.

Live observation (2026-04-24 smoke): Sonnet returned grounded output
where the prose had correct verbatim quotes but the claims' quoted_span
fields were paraphrased AND the retry also paraphrased. The retry
prompt has been tightened to be more emphatic about literal copy-paste;
this normalization handles the simpler rendering-variation cases.
"""
from __future__ import annotations

from donna.security.validator import _normalize, _verbatim_in

# ---------- _normalize ------------------------------------------------


def test_normalize_straightens_curly_single_quotes() -> None:
    """U+2018/2019 → ASCII '. Critical — LLMs frequently emit curly
    apostrophes; source texts (Gutenberg etc) may have straight ones."""
    assert _normalize("don’t") == _normalize("don't")
    assert _normalize("‘hello’") == _normalize("'hello'")


def test_normalize_straightens_curly_double_quotes() -> None:
    assert _normalize("“hello”") == _normalize('"hello"')


def test_normalize_collapses_dashes() -> None:
    """En dash, em dash, and non-breaking hyphen all collapse to ASCII -.
    Prevents "self-aware" != "self–aware" failures."""
    assert _normalize("self–aware") == _normalize("self-aware")
    assert _normalize("self—aware") == _normalize("self-aware")
    assert _normalize("self‑aware") == _normalize("self-aware")


def test_normalize_expands_ellipsis_char_to_three_dots() -> None:
    assert _normalize("to be… or not") == _normalize("to be... or not")


def test_normalize_is_case_and_whitespace_insensitive() -> None:
    """Pre-existing behavior — don't regress."""
    assert _normalize("Hello\n\n  World") == _normalize("hello world")


def test_normalize_unicode_nfc() -> None:
    """é can be encoded as U+00E9 (composed) OR U+0065 U+0301 (decomposed).
    NFC normalizes both to composed. Without it, copy-pasting from certain
    sources vs typed-by-model can produce byte-level mismatches."""
    composed = "café"
    decomposed = "café"
    assert _normalize(composed) == _normalize(decomposed)


# ---------- _verbatim_in with the new normalization ------------------


def test_verbatim_in_accepts_straight_apostrophe_for_curly_source() -> None:
    """Common live pattern: source text has straight apostrophes
    (Gutenberg output), model emits curly apostrophes in quoted_span
    due to training data bias. Before normalization this was a false
    rejection; now it's accepted."""
    chunk_content = "He can't stand civilization because he's been there before."
    span_with_curly = "He can’t stand civilization"  # U+2019
    # Need ≥ 20 chars
    assert len(span_with_curly) >= 20
    assert _verbatim_in(span_with_curly, chunk_content) is True


def test_verbatim_in_accepts_curly_quote_for_straight_source() -> None:
    chunk_content = "He said 'light out for the Territory' and left."
    span_with_curly = "‘light out for the Territory’"
    assert _verbatim_in(span_with_curly, chunk_content) is True


def test_verbatim_in_accepts_ellipsis_char_in_span() -> None:
    chunk_content = "And then... the story continued past the original ending."
    span_with_ellipsis_char = "And then… the story continued"
    assert len(span_with_ellipsis_char) >= 20
    assert _verbatim_in(span_with_ellipsis_char, chunk_content) is True


def test_verbatim_in_still_rejects_actual_paraphrase() -> None:
    """Normalization is rendering-only — real paraphrases still fail.
    The 'content is verbatim' principle holds."""
    chunk_content = "Huck lit out for the Territory to escape civilization."
    paraphrase = "Huck ran away from society to the Territory."
    assert _verbatim_in(paraphrase, chunk_content) is False


def test_verbatim_in_still_rejects_below_min_len() -> None:
    """20-char floor unchanged — no regression."""
    chunk_content = "The long sentence containing many words for matching."
    assert _verbatim_in("short", chunk_content) is False
    # 19 chars — just below the floor
    assert _verbatim_in("nineteen chars long", chunk_content) is False


def test_verbatim_in_accepts_exactly_min_len() -> None:
    """The boundary condition — exactly 20 chars passes."""
    content = "Here is a chunk that has an exact twenty-char span inside it."
    # Extract exactly 20 chars from content
    span = content[10:30]
    assert len(span) == 20
    assert _verbatim_in(span, content) is True


def test_verbatim_in_combined_normalizations() -> None:
    """Multiple normalizations in one span — curly quotes AND different
    case AND extra whitespace — all at once, still verbatim-in."""
    chunk_content = "'I can't stand it. I been there before.' — Huck"
    span_multi_var = "‘I CAN’T stand it.\n\nI been there before.’"
    assert len(span_multi_var) >= 20
    assert _verbatim_in(span_multi_var, chunk_content) is True
