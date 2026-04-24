"""Grounded response robust-parse: code fences, preamble, malformed.

Live bug (2026-04-24): Sonnet returned the grounded JSON wrapped in
a ```json ... ``` markdown code fence despite the prompt's
"no code fences" instruction. `json.loads` choked, `_extract_prose`
returned None → raw JSON fell through to Discord; `validate_grounded`
fell back to `_validate_inline` which emitted noisy "uncited"
fragments from the raw-JSON text split on `. ` boundaries.

Fix: shared `try_parse_grounded_json` helper with three fallbacks:
1. Direct json.loads
2. Strip ```lang ... ``` markdown code fence, retry
3. Find outermost {...} block, retry

And in the validator, when parse fails on JSON-looking input,
surface a single `malformed_json` issue instead of the inline
fallback's noise.

These tests pin the new robustness and the noise suppression.
"""
from __future__ import annotations

import json

from donna.modes.grounded import _extract_prose, _format_output
from donna.security.validator import (
    try_parse_grounded_json,
    validate_grounded,
)
from donna.types import Chunk


def _chunk(cid: str = "chk_1", content: str = "chunk content") -> Chunk:
    return Chunk(
        id=cid, source_id="s1", agent_scope="author_twain",
        work_id=None, publication_date=None, source_type="book",
        content=content, score=1.0,
        chunk_index=0, is_style_anchor=False, source_title="Huck Finn",
    )


# ---------- try_parse_grounded_json -----------------------------------


def test_parse_happy_path_bare_json() -> None:
    raw = json.dumps({"claims": [], "prose": "hi"})
    data = try_parse_grounded_json(raw)
    assert data == {"claims": [], "prose": "hi"}


def test_parse_strips_json_code_fence() -> None:
    """The live prod bug — Sonnet wrapped output in ```json ... ```."""
    raw = '```json\n{\n  "claims": [],\n  "prose": "hello"\n}\n```'
    data = try_parse_grounded_json(raw)
    assert data is not None
    assert data["prose"] == "hello"


def test_parse_strips_unlabeled_code_fence() -> None:
    raw = '```\n{"claims": [], "prose": "yo"}\n```'
    data = try_parse_grounded_json(raw)
    assert data is not None
    assert data["prose"] == "yo"


def test_parse_recovers_from_preamble_and_postamble() -> None:
    """Model adds narrative before and after the JSON — outer-brace
    extraction rescues."""
    raw = (
        "Sure, here is the response you requested:\n"
        '{"claims": [], "prose": "extracted"}\n'
        "Let me know if you need anything else."
    )
    data = try_parse_grounded_json(raw)
    assert data is not None
    assert data["prose"] == "extracted"


def test_parse_returns_non_dict_root_as_is_for_caller_to_reject() -> None:
    """Codex adversarial #5 contract: the validator still needs to
    report `schema_missing` on `[]`, `"string"`, `42`, `null`. Helper
    returns the parsed value verbatim; caller's `isinstance(data, dict)`
    check routes these to the schema_missing branch."""
    assert try_parse_grounded_json("[]") == []
    assert try_parse_grounded_json('"just a string"') == "just a string"
    assert try_parse_grounded_json("42") == 42
    assert try_parse_grounded_json("null") is None  # json null


def test_parse_returns_sentinel_when_no_fallback_succeeds() -> None:
    """Genuine garbage — not any JSON at all — returns a distinct
    sentinel (not `None`, which is valid JSON for `null`). That lets
    the validator route garbage to the malformed_json / inline fallback
    path separately from the non-dict-root path."""
    from donna.security.validator import _PARSE_FAILED
    assert try_parse_grounded_json("not json at all") is _PARSE_FAILED
    assert try_parse_grounded_json("") is _PARSE_FAILED


def test_parse_returns_sentinel_on_fenced_garbage() -> None:
    from donna.security.validator import _PARSE_FAILED
    raw = "```json\nnot actually json\n```"
    assert try_parse_grounded_json(raw) is _PARSE_FAILED


# ---------- _extract_prose ----------------------------------------------


def test_extract_prose_from_code_fenced_response() -> None:
    """Regression test for the live bug — final_text was
    ```json\\n{...}\\n``` and `_extract_prose` returned None so the
    raw fenced JSON went to Discord."""
    raw = (
        "```json\n"
        '{\n'
        '  "claims": [{"text": "x", "citations": ["#chk_1"], "quoted_span": "' + "z" * 25 + '"}],\n'
        '  "prose": "Huck says he can\'t stand civilization [#chk_1]."\n'
        '}\n'
        "```"
    )
    out = _extract_prose(raw)
    assert out == "Huck says he can't stand civilization [#chk_1]."


def test_extract_prose_from_preamble_wrapped_response() -> None:
    raw = (
        'Here is my answer:\n\n'
        '{"claims": [], "prose": "inner prose"}\n\n'
        'Hope that helps!'
    )
    assert _extract_prose(raw) == "inner prose"


# ---------- validate_grounded noise suppression -----------------------


def test_validator_reports_malformed_json_instead_of_inline_noise() -> None:
    """When the model tried to emit JSON but failed (unrecoverable even
    after fence-strip and brace-extract), we report ONE clean issue
    instead of splitting the raw text on `. ` and flagging every
    fragment as 'uncited'. The old behavior buried real validation
    signal under JSON-structural noise."""
    # Truly malformed JSON that none of the fallbacks can rescue
    raw = '{"claims": [{"text": "x", "citations": ["#chk_1",'   # trailing comma, unclosed
    result = validate_grounded(raw, [_chunk()])
    assert not result.ok
    assert len(result.issues) == 1
    assert result.issues[0].reason == "malformed_json"


def test_validator_accepts_code_fenced_valid_response() -> None:
    """Regression: code-fenced but structurally valid JSON validates
    normally — no longer a noise flood, no longer treated as inline."""
    chunk_content = "Aunt Sally she's going to adopt me and sivilize me, and I can't stand it."
    ch = _chunk(cid="chk_1", content=chunk_content)
    raw = (
        "```json\n"
        '{"claims": ['
        '{"text": "Huck resists civilization.",'
        ' "citations": ["#chk_1"],'
        f' "quoted_span": "{chunk_content[:60]}"}}'
        '], "prose": "Huck resists [#chk_1]."}\n'
        "```"
    )
    result = validate_grounded(raw, [ch])
    assert result.ok, f"expected clean validation, got issues: {result.issues}"


def test_validator_still_accepts_bare_json() -> None:
    """The existing happy path still works — fences are an additional
    accepted wrapper, not a replacement."""
    chunk_content = "some content long enough for a twenty-char quoted span."
    ch = _chunk(cid="chk_1", content=chunk_content)
    raw = json.dumps({
        "claims": [{
            "text": "claim",
            "citations": ["#chk_1"],
            "quoted_span": chunk_content[:30],
        }],
        "prose": "prose",
    })
    assert validate_grounded(raw, [ch]).ok


def test_validator_still_falls_back_to_inline_for_prose_plus_markers() -> None:
    """Inline-marker style (no JSON at all, just prose with [#id]) is a
    minority path but valid — must NOT be caught by the new
    'malformed_json' heuristic. Prose text that doesn't start with `{`
    or ``` gets the inline fallback as before."""
    chunk_content = (
        "A long stretch of text from the chunk that the model might "
        "paraphrase in its answer."
    )
    ch = _chunk(cid="chk_1", content=chunk_content)
    # No JSON, just prose with inline markers. This shape is the
    # legitimate inline-fallback case.
    raw = "Huck says he can't stand civilization [#chk_1]. He flees."
    result = validate_grounded(raw, [ch])
    # Either passes (sufficient lexical overlap) or fails with non-malformed
    # reasons — but NOT "malformed_json".
    for issue in result.issues:
        assert issue.reason != "malformed_json"


# ---------- _format_output end-to-end ---------------------------------


def test_format_output_renders_prose_from_fenced_json() -> None:
    """The end-to-end regression test. Prior bug surface to Discord was
    the entire fenced JSON. Fix: prose is extracted, only prose +
    validation badge + sources reach the user."""
    chunk_content = "Huck says civilization is intolerable."
    ch = _chunk(cid="chk_1", content=chunk_content)
    raw = (
        "```json\n"
        '{'
        '"claims": [{"text": "resists",'
        ' "citations": ["#chk_1"],'
        f' "quoted_span": "{chunk_content}"}}'
        '],'
        '"prose": "Huck resists civilization [#chk_1]."'
        '}\n'
        "```"
    )
    validation = validate_grounded(raw, [ch])
    out = _format_output(raw, validation, [ch])

    assert "Huck resists civilization [#chk_1]." in out
    # The JSON schema must NOT leak into the user-visible message
    assert "```json" not in out
    assert '"claims"' not in out
    assert '"quoted_span"' not in out
    assert "✅ validated" in out
