"""Grounded-mode render tests — what hits Discord.

The grounded response schema is designed for the validator: every claim has
`citations` + a verbatim `quoted_span` so we can structurally reject
hallucinations. But that schema is noise to the human reading a DM — they
want the `prose` field, which is the model's stitched-together natural-
language answer with inline `[#chunk_id]` markers.

`_format_output` now parses the JSON and prefers `prose`, falling back to
the raw string when the schema doesn't apply (e.g. model-of-the-moment
decided to respond inline) or is malformed.
"""
from __future__ import annotations

import json

from donna.modes.grounded import _extract_prose, _format_output
from donna.security.validator import ValidationIssue, ValidationResult
from donna.types import Chunk

_OK = ValidationResult(ok=True, issues=[])
_BAD = ValidationResult(
    ok=False,
    issues=[ValidationIssue(claim="fabricated claim", reason="bad_citation:chk_x", cited=["#chk_x"])],
)


def _chunk(cid: str = "chk_1", title: str = "Huck Finn") -> Chunk:
    return Chunk(
        id=cid, source_id="src_1", agent_scope="author_twain",
        work_id=None, publication_date=None, source_type="book",
        content="seed content", score=1.0,
        chunk_index=0, is_style_anchor=False,
        source_title=title,
    )


def test_extract_prose_returns_prose_field() -> None:
    raw = json.dumps({
        "claims": [{"text": "x", "citations": ["#chk_1"], "quoted_span": "y"*25}],
        "prose": "Huck says civilization is uncomfortable [#chk_1].",
    })
    assert _extract_prose(raw) == "Huck says civilization is uncomfortable [#chk_1]."


def test_extract_prose_none_on_unparseable() -> None:
    """Inline-marker-style response (not JSON) parses as None; caller falls
    back to raw so the user still sees the answer."""
    assert _extract_prose("Huck says [#chk_1] that civilization is no good.") is None


def test_extract_prose_none_on_non_dict_root() -> None:
    """json.loads('[]') returns a list; defensively treat as fallback."""
    assert _extract_prose("[]") is None
    assert _extract_prose('"a bare string"') is None


def test_extract_prose_none_on_missing_prose() -> None:
    """Schema-conformant but no prose field → fallback so the raw JSON at
    least reaches the user."""
    raw = json.dumps({"claims": [{"text": "x", "citations": [], "quoted_span": ""}]})
    assert _extract_prose(raw) is None


def test_extract_prose_none_on_blank_prose() -> None:
    raw = json.dumps({"claims": [], "prose": "   "})
    assert _extract_prose(raw) is None


def test_format_output_renders_prose_on_validation_pass() -> None:
    """The live-prod bug: grounded shipped the whole JSON to Discord instead
    of the `prose` field. This pins the new behavior — prose body, validated
    badge, sources footer. No claim-by-claim JSON in the happy path."""
    raw = json.dumps({
        "claims": [{
            "text": "Huck can't stand civilization.",
            "citations": ["#chk_1"],
            "quoted_span": "I can't stand it. I been there before.",
        }],
        "prose": "Huck says he can't stand being sivilized [#chk_1].",
    })
    out = _format_output(raw, _OK, [_chunk()])

    assert "Huck says he can't stand being sivilized [#chk_1]." in out
    # Must NOT dump the raw schema to the user when we have prose
    assert "quoted_span" not in out
    assert '"claims"' not in out
    # Footer still present
    assert "✅" in out and "validated" in out
    assert "Huck Finn" in out


def test_format_output_appends_validation_issues_on_failure() -> None:
    """When validation fails, the user gets prose + an issues breakdown so
    they can see what the model did wrong. No claim-by-claim JSON — the
    issue list is already the actionable bit."""
    raw = json.dumps({
        "claims": [{
            "text": "fabricated claim",
            "citations": ["#chk_x"],
            "quoted_span": "never appears in corpus",
        }],
        "prose": "Here is a fabricated answer [#chk_x].",
    })
    out = _format_output(raw, _BAD, [_chunk()])

    assert "Here is a fabricated answer [#chk_x]." in out
    assert "Validation issues:" in out
    assert "bad_citation:chk_x" in out
    assert "fabricated claim" in out
    assert "⚠️" in out and "partial validation" in out


def test_format_output_falls_back_to_raw_on_unparseable() -> None:
    """Model responded in inline-marker style (valid output per the fallback
    validator). Render raw text so the answer still reaches the user —
    instead of "" or a crash."""
    raw = "Huck says [#chk_1] that being sivilized is unbearable."
    out = _format_output(raw, _OK, [_chunk()])

    assert raw in out
    assert "✅" in out and "validated" in out


def test_format_output_falls_back_when_prose_missing() -> None:
    """Schema-conformant but no prose field — fall back to raw JSON. Better
    ugly than empty."""
    raw = json.dumps({
        "claims": [{"text": "x", "citations": ["#chk_1"], "quoted_span": "z"*25}],
    })
    out = _format_output(raw, _OK, [_chunk()])

    # Raw JSON reaches the user (degraded but non-empty)
    assert '"claims"' in out
    assert "✅" in out and "validated" in out


def test_format_output_emoji_glyph_outside_italic_span() -> None:
    """V50-7 (2026-05-01): the validator badge glyph (⚠️ / ✅) must NOT be
    wrapped inside `_..._` italic markers — Slack mangles emoji adjacent to
    italic markers and renders ⚠️ as literal `:warning:` text. Operator hit
    this in v0.5.0 live smoke. The fix hoists the glyph out of the italic
    span so it renders as an emoji glyph followed by italic-formatted label.
    """
    raw = json.dumps({"claims": [], "prose": "answer"})
    out = _format_output(raw, _OK, [_chunk()])
    # Negative assertion: glyph immediately followed by underscore
    # (the broken layout) must NOT appear.
    assert "_✅" not in out, (
        f"validator badge glyph wrapped in italic span (V50-7): {out!r}"
    )
    # Positive assertion: glyph followed by space + underscore
    # (the fixed layout) IS present.
    assert "✅ _validated" in out


def test_format_output_failure_glyph_outside_italic_span() -> None:
    """V50-7 (2026-05-01): same regression guard for the failure-case glyph."""
    raw = json.dumps({"claims": [], "prose": "fabricated"})
    out = _format_output(raw, _BAD, [_chunk()])
    assert "_⚠️" not in out, (
        f"validator badge glyph wrapped in italic span (V50-7): {out!r}"
    )
    assert "⚠️ _partial validation" in out


def test_format_output_never_empty_even_on_blank_prose() -> None:
    """Regression guard: a blank `prose` field must NOT produce an empty
    Discord message. The bot's 1500-char truncation + empty final_text
    could silently send nothing. Instead: fall back to raw."""
    raw = json.dumps({"claims": [], "prose": ""})
    out = _format_output(raw, _OK, [_chunk()])

    # Something renders — the raw JSON in this degraded case
    assert out.strip() != ""
    assert "✅" in out and "validated" in out
