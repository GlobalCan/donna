"""Grounded mode — strict-citation Q&A over a scope's corpus.

Rewritten to use JobContext (Codex review #2+#15 — every mode shares the same
primitives: model_step, checkpoint, consent, etc.).

Codex review #11: response schema now requires a `quoted_span` per claim that
must appear verbatim in the cited chunk. Weak lexical overlap was theater;
this is constrained transparency.
"""
from __future__ import annotations

from ..agent.compose import compose_system
from ..agent.context import JobContext
from ..agent.model_adapter import model
from ..logging import get_logger
from ..observability import otel
from ..security.validator import validate_grounded
from ..types import JobMode, ModelTier
from .retrieval import retrieve_knowledge

log = get_logger(__name__)


GROUNDED_RESPONSE_SCHEMA = """
Respond with valid JSON matching this schema exactly:
{
  "claims": [
    {
      "text": "<natural-language claim>",
      "citations": ["<chunk_id>", ...],
      "quoted_span": "<a LITERAL COPY-PASTE substring from one of the cited chunks — at least 20 characters, character-for-character verbatim including punctuation, capitalization, and spelling>"
    },
    ...
  ],
  "prose": "<stitched-together natural-language answer with [#chunk_id] markers inline>"
}

Rules — read these carefully before writing output:

1. Every claim MUST cite at least one chunk id from the retrieved context.
2. Every claim's `quoted_span` MUST be a LITERAL substring of one of its
   cited chunks — not a paraphrase, not a summary, not a rewording for
   clarity, not even a punctuation tweak. Think of it as copy-paste with
   your cursor: find the exact text in the chunk, select ≥20 characters,
   and paste into quoted_span.
3. If you cannot find a ≥20-char literal substring in the chunk that
   supports a given claim, OMIT THE CLAIM ENTIRELY. A missing claim is
   strictly better than a non-verbatim quoted_span — the validator rejects
   non-verbatim spans and the whole response goes through an expensive
   retry cycle.
4. Never fabricate chunk ids. Cite only ids present in the retrieved set.
5. Output ONLY the JSON object. No preamble, no markdown code fences
   (no ```json), no closing commentary. The first character of your
   response should be `{` and the last should be `}`.
"""


async def run_grounded(ctx: JobContext) -> None:
    """Entry point invoked by agent.loop.run_job for JobMode.GROUNDED."""
    # Resume short-circuit — if a prior worker reached done=True + checkpointed,
    # but died before finalize, this worker inherits that state. Re-running
    # retrieval + the model call would waste spend and potentially overwrite
    # final_text with a different answer. Context manager will still finalize
    # on exit (delivering the pre-existing final_text). Chat mode has the same
    # guard via its loop condition.
    if ctx.state.done:
        return

    scope = ctx.job.agent_scope
    question = ctx.job.task

    ctx.check_cancelled()
    retrieval = await retrieve_knowledge(scope=scope, query=question, top_k=8)
    chunks = retrieval.get("chunks", [])
    if retrieval.get("tainted") and not ctx.state.tainted:
        ctx.state.tainted = True
        otel.set_attr("agent.job.tainted", True)

    if not chunks:
        ctx.state.final_text = (
            f"[grounded · refused] I don't have {scope} material on this topic."
        )
        ctx.state.done = True
        ctx.checkpoint_or_raise()
        return

    system_blocks = compose_system(
        scope=scope, task=question, mode=JobMode.GROUNDED,
        retrieved_chunks=chunks,
    )
    system_blocks[-1]["text"] += "\n\n" + GROUNDED_RESPONSE_SCHEMA

    with otel.span("grounded.generate", **{"agent.scope": scope}):
        result = await ctx.model_step(
            system_blocks=system_blocks,
            messages=[{"role": "user", "content": question}],
            tier=ModelTier.STRONG,
            max_tokens=2048,
        )

    # Log a short preview of the raw response so diagnostic runs (and the
    # watchdog / trace store) can see what the model actually emitted without
    # dumping it into checkpoint_state. 300 chars is enough to tell whether
    # the model used code fences, curly quotes, or paraphrased quoted_spans.
    log.info(
        "grounded.model_response",
        job_id=ctx.job.id, scope=scope,
        preview=result.text[:300], length=len(result.text),
    )

    validation = validate_grounded(result.text, chunks)

    ctx.check_cancelled()

    # One retry with a tighter instruction if validation failed
    if not validation.ok:
        issue_summary = "; ".join(
            f"{i.reason}: {i.claim[:80]}" for i in validation.issues[:5]
        )
        fixup = (
            f"Previous response failed citation validation. Issues: {issue_summary}.\n\n"
            "Regenerate with strict verbatim quoted_spans. For each claim, the "
            "`quoted_span` field MUST be a LITERAL COPY-PASTE of characters "
            "from the cited chunk — NOT a paraphrase, NOT a summary, NOT "
            "rewording for clarity. Find text in the chunk; copy it verbatim "
            "(including punctuation); paste into quoted_span.\n\n"
            "If you cannot find a ≥20-char literal substring that supports the "
            "claim, OMIT THE CLAIM ENTIRELY. A missing claim is always better "
            "than a non-verbatim one."
        )
        system_blocks[-1]["text"] += "\n\n" + fixup
        with otel.span("grounded.regenerate", **{"agent.scope": scope}):
            result = await ctx.model_step(
                system_blocks=system_blocks,
                messages=[{"role": "user", "content": question}],
                tier=ModelTier.STRONG,
                max_tokens=2048,
            )
        log.info(
            "grounded.model_response_retry",
            job_id=ctx.job.id, scope=scope,
            preview=result.text[:300], length=len(result.text),
        )
        validation = validate_grounded(result.text, chunks)

    ctx.state.final_text = _format_output(result.text, validation, chunks)
    ctx.state.done = True
    ctx.checkpoint_or_raise()


def _format_output(raw: str, validation, chunks) -> str:
    """Render the grounded response for Discord.

    Prefers the model's `prose` field (human-readable answer with inline
    [#chunk_id] markers) over the full JSON schema that's meant for the
    validator, not the user. Falls back to the raw response when it doesn't
    parse (inline-marker style) or lacks a usable `prose` key. On validation
    failure, appends the claim-by-claim issue breakdown so the operator can
    audit what the model did wrong.
    """
    # V50-7 (2026-05-01): emoji glyphs hoisted OUT of the italic span. When
    # ⚠️ was inside `_..._` Slack's renderer mangled it to literal
    # `:warning:` text adjacent to italic markers (operator-reported in
    # v0.5.0 live smoke). Putting the glyph before the italic span keeps
    # the badge readable in Slack while still rendering in botctl/CLI.
    badge_glyph = "✅" if validation.ok else "⚠️"
    badge_label = "validated" if validation.ok else "partial validation"
    sources = sorted({c.source_title or c.source_id for c in chunks})

    out = _extract_prose(raw) or raw
    if not validation.ok:
        issues = "\n".join(
            f"- {i.reason}: {i.claim[:120]}" for i in validation.issues[:10]
        )
        out += f"\n\n_Validation issues:_\n{issues}"
    out += (
        f"\n\n{badge_glyph} _{badge_label} · "
        f"sources: {', '.join(sources[:10])}_"
    )
    return out


def _extract_prose(raw: str) -> str | None:
    """Parse `raw` as the grounded JSON schema and return its `prose` field.

    Uses the same robust-parse helper as the validator, so a model that
    wraps its JSON in a ``` code fence or adds preamble/postamble text
    still gets its prose extracted correctly. Live bug (2026-04-24):
    Sonnet returned ```json ... ``` despite the "no code fences"
    instruction, which silently fell through to raw-JSON rendering +
    noisy inline-fallback validator output.

    Returns None when:
    - None of the parse fallbacks produce a dict (inline-marker style,
      or truly malformed)
    - `prose` key is missing, non-string, or blank

    Caller falls back to the raw string in those cases.
    """
    from ..security.validator import try_parse_grounded_json
    data = try_parse_grounded_json(raw)
    if not isinstance(data, dict):
        return None
    prose = data.get("prose")
    if isinstance(prose, str) and prose.strip():
        return prose.strip()
    return None


# Kept for test compatibility; prefer run_grounded() going forward.
async def answer_grounded(scope: str, question: str, *, job_id: str | None = None):
    """Legacy API — returns a dict instead of updating a JobContext."""
    retrieval = await retrieve_knowledge(scope=scope, query=question, top_k=8)
    chunks = retrieval.get("chunks", [])
    if not chunks:
        return {
            "mode": "grounded", "refused": True,
            "reason": f"I don't have material from {scope} on this topic.",
        }
    system_blocks = compose_system(
        scope=scope, task=question, mode=JobMode.GROUNDED, retrieved_chunks=chunks,
    )
    system_blocks[-1]["text"] += "\n\n" + GROUNDED_RESPONSE_SCHEMA
    result = await model().generate(
        system=system_blocks, messages=[{"role": "user", "content": question}],
        tier=ModelTier.STRONG, job_id=job_id, max_tokens=2048,
    )
    validation = validate_grounded(result.text, chunks)
    return {
        "mode": "grounded", "scope": scope, "raw": result.text,
        "validated": validation.ok,
        "issues": [{"claim": i.claim[:200], "reason": i.reason} for i in validation.issues],
        "chunks_used": [c.id for c in chunks],
        "sources": sorted({c.source_title or c.source_id for c in chunks}),
    }
