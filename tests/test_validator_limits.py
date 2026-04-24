"""Pin the known limits of the grounded quoted_span validator.

The validator is structural, not semantic. It checks:
  1. Every claim has at least one citation
  2. The cited chunk_id exists in the retrieved set
  3. The `quoted_span` is a verbatim substring (≥20 chars, case/whitespace
     normalized) of the cited chunk

It does NOT check that the quoted_span semantically supports the claim —
that's the "constrained transparency" compromise from Codex #11. A semantic
check would require an NLI sidecar (separate LLM call per claim), which is
expensive and was deferred to v1.2.

These tests pin the limit so future changes don't accidentally:
  (a) drop the verbatim check and regress to the old lexical-overlap theater
  (b) add a silent semantic check that could reject legitimate paraphrase-
      like behavior without a design discussion

The attack shape this accepts: a model that quotes a real passage from
the right chunk but makes an unrelated claim. User sees both, judges for
themselves. The exfiltration vectors Codex worried about (hallucinated
chunk IDs, uncited attributions) are structurally blocked.
"""
from __future__ import annotations

import json

from donna.security.validator import validate_grounded
from donna.types import Chunk


def _chunk(cid: str, content: str) -> Chunk:
    return Chunk(
        id=cid, source_id="src_1", agent_scope="author_twain",
        work_id=None, publication_date=None, source_type="book",
        content=content, score=1.0,
        chunk_index=0, is_style_anchor=False,
        source_title="Huck Finn",
    )


def test_validator_accepts_verbatim_span_unrelated_to_claim() -> None:
    """Known limitation — verbatim substring is sufficient; semantic
    relevance is NOT checked. If this test ever starts failing, someone
    added semantic validation without updating the doc or the Codex #11
    'constrained transparency' note."""
    chunks = [_chunk(
        "chk_1",
        "Huck lit out for the Territory ahead of the rest. The moon was "
        "bright that night. Tom said nothing.",
    )]
    response = json.dumps({
        "claims": [{
            "text": "Huck thought cats were superior to dogs.",
            "citations": ["#chk_1"],
            # Verbatim substring of the chunk, ≥20 chars, but has zero to do
            # with cats or dogs. Validator has no way to know.
            "quoted_span": "Huck lit out for the Territory ahead of the rest.",
        }],
        "prose": "Some unsupported claim here [#chk_1].",
    })
    result = validate_grounded(response, chunks)
    assert result.ok, (
        "Validator is structural only — verbatim span is sufficient by design. "
        "If this fails, semantic validation was added without a design discussion."
    )


def test_validator_rejects_non_verbatim_paraphrase() -> None:
    """Paraphrase — even a true one — is rejected if not verbatim. This is
    the 'constrained transparency' strictness: you can't approximate a
    quote, you must quote it. Catches a real class of hallucinations where
    the model summarizes a chunk's content and claims it's a quote."""
    chunks = [_chunk("chk_1", "The moon was bright that night.")]
    response = json.dumps({
        "claims": [{
            "text": "The sky was illuminated.",
            "citations": ["#chk_1"],
            # Paraphrase of the chunk — not verbatim
            "quoted_span": "The moonlight was illuminating the sky brightly that evening.",
        }],
        "prose": "Nope.",
    })
    result = validate_grounded(response, chunks)
    assert not result.ok
    assert result.issues[0].reason in ("quoted_span_not_in_chunk", "bad_citation:chk_1")


def test_validator_rejects_span_shorter_than_20_chars() -> None:
    """The 20-char floor prevents single-word 'quotes' from passing validation.
    A 5-char verbatim match is indistinguishable from coincidence."""
    chunks = [_chunk("chk_1", "The moon was bright that night indeed.")]
    response = json.dumps({
        "claims": [{
            "text": "Something about the moon.",
            "citations": ["#chk_1"],
            "quoted_span": "moon",  # 4 chars — below threshold
        }],
        "prose": "...",
    })
    result = validate_grounded(response, chunks)
    assert not result.ok


def test_validator_accepts_case_and_whitespace_insensitive_verbatim() -> None:
    """Intentional leniency — whitespace collapse and case folding are
    normalized. A model that quotes with extra spaces or different
    capitalization still passes. This is the fuzziness allowance."""
    chunks = [_chunk(
        "chk_1",
        "Aunt Sally she's going to adopt me and sivilize me, and I can't stand it.",
    )]
    response = json.dumps({
        "claims": [{
            "text": "Huck resists civilization.",
            "citations": ["#chk_1"],
            # Different case, extra spaces — still matches after normalization
            "quoted_span": "aunt sally  she's going to adopt me and sivilize me, and i can't stand it.",
        }],
        "prose": "Huck resists civilization [#chk_1].",
    })
    result = validate_grounded(response, chunks)
    assert result.ok


def test_validator_rejects_citation_to_nonexistent_chunk() -> None:
    """Hallucinated chunk_id — citation points at a chunk that wasn't
    retrieved. Validator catches this via chunk_by_id lookup."""
    chunks = [_chunk("chk_1", "Real chunk content here.")]
    response = json.dumps({
        "claims": [{
            "text": "Some claim.",
            "citations": ["#chk_nonexistent"],
            "quoted_span": "doesn't matter — chunk id is fake",
        }],
        "prose": "...",
    })
    result = validate_grounded(response, chunks)
    assert not result.ok
    assert "bad_citation" in result.issues[0].reason


def test_validator_rejects_empty_citations() -> None:
    chunks = [_chunk("chk_1", "content")]
    response = json.dumps({
        "claims": [{"text": "uncited claim", "citations": [], "quoted_span": "ignored"}],
        "prose": "...",
    })
    result = validate_grounded(response, chunks)
    assert not result.ok
    assert result.issues[0].reason == "uncited"


def test_validator_rejects_missing_quoted_span() -> None:
    """An otherwise-valid claim structure without quoted_span fails —
    citation without evidence is as bad as no citation."""
    chunks = [_chunk("chk_1", "plenty of content for a quote here in this sentence")]
    response = json.dumps({
        "claims": [{"text": "claim", "citations": ["#chk_1"]}],  # no quoted_span
        "prose": "...",
    })
    result = validate_grounded(response, chunks)
    assert not result.ok
    assert result.issues[0].reason == "quoted_span_missing"
