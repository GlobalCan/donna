"""Grounding validator — catches uncited, invalid chunk ids, weak support."""
from __future__ import annotations

import json

from donna.security.validator import validate_grounded, validate_debate_turn
from donna.types import Chunk


def _c(id_: str, content: str, title: str = "Test Book") -> Chunk:
    return Chunk(
        id=id_, source_id="src_1", agent_scope="author_test",
        work_id="w1", publication_date="2020-01-01", source_type="book",
        content=content, score=1.0, chunk_index=0, is_style_anchor=False,
        source_title=title,
    )


def test_uncited_claim_fails() -> None:
    chunks = [_c("chunk_1", "Lewis emphasized outsiders exploiting market structure.")]
    resp = json.dumps({
        "claims": [{"text": "Lewis loves coffee.", "citations": []}],
        "prose": "Lewis loves coffee.",
    })
    r = validate_grounded(resp, chunks)
    assert not r.ok
    assert any("uncited" in i.reason for i in r.issues)


def test_bad_citation_fails() -> None:
    chunks = [_c("chunk_1", "He wrote that outsiders often have the clearest view.")]
    resp = json.dumps({
        "claims": [{"text": "Outsiders see clearest.", "citations": ["#chunk_99"]}],
        "prose": "Outsiders see clearest [#chunk_99].",
    })
    r = validate_grounded(resp, chunks)
    assert not r.ok
    assert any("bad_citation" in i.reason for i in r.issues)


def test_valid_citation_passes() -> None:
    """Pass-2 updated schema: response must include quoted_span (verbatim
    substring of the cited chunk) for the claim to validate."""
    chunks = [_c("chunk_1",
                 "Lewis argues that outsiders systematically see what insiders miss, "
                 "exploiting structural blindspots in modern markets.")]
    resp = json.dumps({
        "claims": [{
            "text": "Outsiders exploit structural blindspots in markets.",
            "citations": ["#chunk_1"],
            "quoted_span": "exploiting structural blindspots in modern markets",
        }],
        "prose": "Outsiders exploit structural blindspots [#chunk_1].",
    })
    r = validate_grounded(resp, chunks)
    assert r.ok, f"expected ok, got issues: {r.issues}"


def test_debate_attack_without_quote_is_flagged() -> None:
    """Attacks that invent a position AND share no substantive 10-char
    substring with the actual prior turn must be flagged. (Post-Pass-2 the
    matcher normalizes whitespace+case and allows 10-char fuzzy overlap, so
    the test case needs to be blatant — imputing views with zero textual
    grounding.)"""
    prior = [
        {"round": 1, "scope": "lewis",
         "content": "Casino capitalism turned Wall Street into a speculative arena."},
    ]
    # Wholly different vocabulary — turn invents a Lewis position on crypto
    # which shares no meaningful substring with the actual prior text.
    turn = "Lewis argues that cryptocurrency is a genuine revolution in money."
    issues = validate_debate_turn(turn, prior, current_scope="dalio")
    assert any("attacks_without_quote" in i for i in issues), \
        f"expected flag; got: {issues}"


def test_debate_quote_match_passes() -> None:
    prior = [
        {"round": 1, "scope": "lewis",
         "content": "Markets are efficient only if you define efficiency narrowly."},
    ]
    turn = (
        'Lewis claims "efficiency only if you define efficiency narrowly". '
        "That sleight-of-hand overstates the case."
    )
    issues = validate_debate_turn(turn, prior, current_scope="dalio")
    assert not issues
