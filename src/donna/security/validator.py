"""Grounded-mode citation validator.

Parses grounded response (JSON), checks every claim has a citation, and each
citation's chunk contains enough lexical overlap to plausibly support the claim.

This is not perfect entailment — it's a cheap structural guardrail that catches
the common failure modes: empty citations, hallucinated chunk IDs, claims that
have nothing to do with what they cite.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..types import Chunk

CITATION_RE = re.compile(r"#([A-Za-z0-9_]+)")


@dataclass
class ValidationIssue:
    claim: str
    reason: str
    cited: list[str]


@dataclass
class ValidationResult:
    ok: bool
    issues: list[ValidationIssue]


def validate_grounded(response_json: str, chunks: list[Chunk]) -> ValidationResult:
    chunk_by_id = {c.id: c for c in chunks}
    try:
        data = json.loads(response_json)
    except json.JSONDecodeError:
        # Accept pure-prose responses that use inline [#id] markers as a fallback
        return _validate_inline(response_json, chunk_by_id)

    # Codex adversarial scan #5: json.loads("[]") or json.loads('"hello"')
    # returns a non-dict and would AttributeError on data.get(...). Surface
    # as a schema issue instead of crashing grounded mode.
    if not isinstance(data, dict):
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue(
                claim=f"(non-dict json root: {type(data).__name__})",
                reason="schema_missing", cited=[],
            )],
        )

    issues: list[ValidationIssue] = []
    claims = data.get("claims", [])
    if not isinstance(claims, list) or not claims:
        return ValidationResult(
            ok=False,
            issues=[ValidationIssue(claim="(no claims array)", reason="schema_missing", cited=[])],
        )
    for c in claims:
        text = (c or {}).get("text", "").strip()
        cits = (c or {}).get("citations", []) or []
        quoted_span = (c or {}).get("quoted_span", "").strip()
        if not text:
            continue
        if not cits:
            issues.append(ValidationIssue(claim=text, reason="uncited", cited=[]))
            continue

        # Codex #11 fix — prefer verbatim quoted_span check over lexical overlap.
        span_ok = False
        bad_citations: list[str] = []
        for cid in cits:
            cid_clean = str(cid).lstrip("#")
            ch = chunk_by_id.get(cid_clean)
            if ch is None:
                bad_citations.append(cid_clean)
                continue
            if quoted_span and _verbatim_in(quoted_span, ch.content):
                span_ok = True
                break

        if bad_citations and not span_ok:
            issues.append(ValidationIssue(
                claim=text, reason=f"bad_citation:{','.join(bad_citations)}", cited=cits,
            ))
            continue

        if not span_ok:
            reason = ("quoted_span_missing" if not quoted_span
                      else "quoted_span_not_in_chunk")
            issues.append(ValidationIssue(claim=text, reason=reason, cited=cits))

    return ValidationResult(ok=not issues, issues=issues)


def _verbatim_in(span: str, chunk_text: str, min_len: int = 20) -> bool:
    """Is `span` a literal (whitespace-normalized, case-insensitive) substring
    of `chunk_text`, at least `min_len` chars? Codex #11 enforcement."""
    if len(span) < min_len:
        return False
    s_norm = " ".join(span.lower().split())
    c_norm = " ".join(chunk_text.lower().split())
    return s_norm in c_norm


def _validate_inline(text: str, chunk_by_id: dict[str, Chunk]) -> ValidationResult:
    # Split on sentence-ish punctuation and check each sentence has >= 1 [#id]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    issues: list[ValidationIssue] = []
    for s in sentences:
        s = s.strip()
        if len(s) < 20:
            continue
        ids_in_s = CITATION_RE.findall(s)
        if not ids_in_s:
            issues.append(ValidationIssue(claim=s, reason="uncited", cited=[]))
            continue
        for cid in ids_in_s:
            ch = chunk_by_id.get(cid)
            if ch is None:
                issues.append(ValidationIssue(claim=s, reason=f"bad_citation:{cid}", cited=ids_in_s))
                break
            if not _supports(ch.content, s):
                issues.append(ValidationIssue(claim=s, reason=f"weak_support:{cid}", cited=ids_in_s))
                break
    return ValidationResult(ok=not issues, issues=issues)


def _supports(chunk_text: str, claim_text: str) -> bool:
    """Cheap lexical overlap check — at least 2 content words from the claim
    (4+ chars, not stopwords) must appear in the chunk."""
    stop = {
        "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
        "to", "of", "in", "on", "at", "for", "with", "by", "from", "about", "that",
        "this", "these", "those", "as", "so", "it", "its",
    }
    claim_words = {w.lower() for w in re.findall(r"\w+", claim_text) if len(w) > 3 and w.lower() not in stop}
    chunk_lower = chunk_text.lower()
    overlap = sum(1 for w in claim_words if w in chunk_lower)
    return overlap >= 2


# Debate-turn validator -----------------------------------------------------

def validate_debate_turn(turn_text: str, prior_turns: list[dict], current_scope: str) -> list[str]:
    """Return a list of issues with a debate turn.

    Checks:
     - When attacking an opposing speaker, did the turn quote their prior text?
     - Did the turn use citation markers from its OWN scope only (validated by caller via chunk IDs)?

    Codex audit: prior version required a literal 15-char substring match which
    false-positive'd on legitimate paraphrases and punctuation-normalized quotes.
    Now: normalize both texts (lowercase + collapse punctuation+whitespace),
    accept a 10-char fuzzy substring OR a quoted span detected in the turn.
    """
    issues: list[str] = []

    # Scopes referenced with claim/argue/say/believe/think verbs
    for t in prior_turns:
        if t["scope"] == current_scope:
            continue
        other = t["scope"]
        if other.lower() not in turn_text.lower():
            continue
        if not re.search(
            rf"{re.escape(other)}[^.]*(argue|claim|say|believe|think|insist|contend)",
            turn_text, re.IGNORECASE,
        ):
            continue

        # Accept: literal quote (any length ≥ 5 inside "..." or '...')
        quoted_spans = re.findall(r'"([^"]{5,})"|\'([^\']{5,})\'', turn_text)
        quoted_flat = [q for pair in quoted_spans for q in pair if q]
        if any(
            _norm(q) in _norm(t["content"]) for q in quoted_flat
        ):
            continue

        # Or: fuzzy 10-char normalized substring overlap
        if _has_substring_overlap(
            _norm(turn_text), _norm(t["content"]), min_len=10,
        ):
            continue

        issues.append(f"attacks_without_quote:{other}")
    return issues


def _norm(s: str) -> str:
    """Normalize for quote-match: lowercase, collapse whitespace, strip punctuation."""
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _has_substring_overlap(a: str, b: str, min_len: int = 15) -> bool:
    # Codex adversarial scan #9: this is O(len(b) * len(a)) and runs on
    # unbounded model text during debate-turn validation. A long prior turn
    # plus a long current turn could block the worker loop for seconds.
    # Cap both inputs — debate turns shouldn't need >50k chars of overlap
    # scanning, and anything longer is almost certainly noise.
    _MAX_SCAN = 50_000
    a = a[:_MAX_SCAN]
    b = b[:_MAX_SCAN]
    if len(a) < min_len or len(b) < min_len:
        return False
    for i in range(len(b) - min_len):
        sub = b[i : i + min_len]
        if sub in a:
            return True
    return False
