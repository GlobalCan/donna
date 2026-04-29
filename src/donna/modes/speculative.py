"""Speculative mode — extrapolate from a scope's voice, clearly labeled.

Rewritten to use JobContext (unified execution model).
"""
from __future__ import annotations

from ..agent.compose import compose_system
from ..agent.context import JobContext
from ..agent.model_adapter import model
from ..logging import get_logger
from ..memory import prompts as prompts_mod
from ..memory.db import connect
from ..observability import otel
from ..types import JobMode, ModelTier
from .retrieval import retrieve_knowledge

log = get_logger(__name__)


async def run_speculative(ctx: JobContext) -> None:
    # Resume short-circuit — same rationale as grounded: avoid re-running
    # retrieval + the model call when a prior worker already produced
    # final_text and checkpointed done=True.
    if ctx.state.done:
        return

    scope = ctx.job.agent_scope
    question = ctx.job.task

    conn = connect()
    try:
        prompt_row = prompts_mod.active_prompt(conn, scope)
    finally:
        conn.close()

    if not prompt_row or not prompt_row.get("speculation_allowed"):
        ctx.state.final_text = (
            f"[speculative · refused] Speculation is disabled for scope '{scope}'. "
            "Enable via agent_prompts.speculation_allowed = 1."
        )
        ctx.state.done = True
        ctx.checkpoint_or_raise()
        return

    ctx.check_cancelled()
    anchors_res = await retrieve_knowledge(
        scope=scope, query=question, top_k=5, style_anchors_only=True,
    )
    ctx_res = await retrieve_knowledge(scope=scope, query=question, top_k=8)
    if (anchors_res.get("tainted") or ctx_res.get("tainted")) and not ctx.state.tainted:
        ctx.state.tainted = True
        otel.set_attr("agent.job.tainted", True)

    system_blocks = compose_system(
        scope=scope, task=question, mode=JobMode.SPECULATIVE,
        retrieved_chunks=ctx_res.get("chunks", []),
        style_anchors=anchors_res.get("chunks", []),
    )

    with otel.span("speculative.generate", **{"agent.scope": scope}):
        result = await ctx.model_step(
            system_blocks=system_blocks,
            messages=[{"role": "user", "content": question}],
            tier=ModelTier.STRONG,
            max_tokens=2048,
        )

    # Phrasing guardrail: flag banned assertions
    banned = ["thinks that", "says that", "believes that", "argues that"]
    flags = [p for p in banned if p in result.text.lower()]

    sources = sorted({
        c.source_title or c.source_id
        for c in (ctx_res.get("chunks", []) + anchors_res.get("chunks", []))
    })

    label = f"🔮 SPECULATIVE — extrapolated from {scope}'s documented patterns, not their actual view"
    body = result.text
    if flags:
        body += f"\n\n_⚠ phrasing flagged: {', '.join(flags)}_"
    body += f"\n\n_Calibration sources: {', '.join(sources[:10])}_"

    ctx.state.final_text = f"{label}\n\n{body}"
    ctx.state.done = True
    ctx.checkpoint_or_raise()


# Legacy API for existing tests
async def answer_speculative(scope: str, question: str, *, job_id: str | None = None):
    conn = connect()
    try:
        prompt_row = prompts_mod.active_prompt(conn, scope)
    finally:
        conn.close()
    if not prompt_row or not prompt_row.get("speculation_allowed"):
        return {
            "mode": "speculative", "refused": True,
            "reason": f"Speculation is disabled for scope '{scope}'. "
                      "Enable it per-scope via agent_prompts.speculation_allowed = 1.",
        }
    anchors_res = await retrieve_knowledge(
        scope=scope, query=question, top_k=5, style_anchors_only=True,
    )
    ctx_res = await retrieve_knowledge(scope=scope, query=question, top_k=8)
    system_blocks = compose_system(
        scope=scope, task=question, mode=JobMode.SPECULATIVE,
        retrieved_chunks=ctx_res.get("chunks", []),
        style_anchors=anchors_res.get("chunks", []),
    )
    result = await model().generate(
        system=system_blocks, messages=[{"role": "user", "content": question}],
        tier=ModelTier.STRONG, job_id=job_id, max_tokens=2048,
    )
    banned = ["thinks that", "says that", "believes that", "argues that"]
    flags = [p for p in banned if p in result.text.lower()]
    return {
        "mode": "speculative", "scope": scope,
        "label": f"🔮 SPECULATIVE — extrapolated from {scope}'s documented patterns",
        "text": result.text, "flagged_phrasings": flags,
        "calibration": sorted({
            c.source_title or c.source_id
            for c in (ctx_res.get("chunks", []) + anchors_res.get("chunks", []))
        }),
    }
