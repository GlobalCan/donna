"""Agent execution entrypoint.

This file used to have a two-headed split (generic loop + mode dispatch).
Codex adversarial review #2+#15 flagged that as architectural fracture.
NOW: every mode is a graph variant over the same primitives in JobContext.
This file is thin orchestration; the real work lives in context.py and
modes/*.py.
"""
from __future__ import annotations

from ..config import settings
from ..logging import get_logger
from ..observability import otel
from ..tools.registry import anthropic_tool_defs
from ..types import JobMode, ModelTier
from .compose import compose_system
from .context import JobContext

log = get_logger(__name__)


async def run_job(job_id: str, worker_id: str, **_ignored) -> None:
    """Execute a job to completion or checkpoint. Dispatch by mode."""
    async with JobContext.open(job_id, worker_id) as ctx:
        if ctx is None:
            return
        mode = ctx.state.mode
        if mode == JobMode.GROUNDED:
            from ..modes.grounded import run_grounded
            await run_grounded(ctx)
        elif mode == JobMode.SPECULATIVE:
            from ..modes.speculative import run_speculative
            await run_speculative(ctx)
        elif mode == JobMode.DEBATE:
            from ..modes.debate import run_debate_in_context
            await run_debate_in_context(ctx)
        elif mode == JobMode.VALIDATE:
            # v0.7.1: URL-bounded grounded critique. Single URL only;
            # SSRF-safe fetch; ephemeral chunks (not persisted to
            # knowledge_chunks); GROUNDED_RESPONSE_SCHEMA + verbatim
            # quoted_span validator on the output.
            from ..modes.validate import run_validate
            await run_validate(ctx)
        else:  # CHAT and default
            await _run_chat(ctx)


async def _run_chat(ctx: JobContext) -> None:
    """Chat / agent-loop mode: iterate LLM ↔ tools until end_turn or budget."""
    s = settings()
    max_tool_calls = s.max_tool_calls_per_job
    scope = ctx.job.agent_scope
    task = ctx.job.task

    # Session memory: load prior conversation in this Discord thread once
    # at loop entry. The `messages` table is populated by
    # JobContext.finalize at the end of each clean (non-tainted) job, so
    # entries here are from PREVIOUS jobs + clean. Per-iteration re-fetch
    # would also be safe but unnecessary — the loop runs within a single
    # job and finalize hasn't fired yet.
    session_history: list[dict] = []
    if ctx.job.thread_id:
        from ..memory import threads as threads_mod
        from ..memory.db import connect as _connect
        _conn = _connect()
        try:
            session_history = threads_mod.recent_messages(
                _conn, ctx.job.thread_id, limit=8,
            )
        finally:
            _conn.close()

    while not ctx.state.done and ctx.state.tool_calls_count < max_tool_calls:
        # Check user-initiated cancellation between iterations. Raises
        # JobCancelled which the context manager catches + checkpoints.
        ctx.check_cancelled()

        # Shared primitive: compaction
        await ctx.maybe_compact()

        # Shared primitive: retrieval (if scope has a corpus)
        chunks, examples, anchors, retrieval_tainted = await _load_scoped_context(scope, task)
        if retrieval_tainted and not ctx.state.tainted:
            ctx.state.tainted = True
            otel.set_attr("agent.job.tainted", True)

        # Shared primitive: compose
        system_blocks = compose_system(
            scope=scope, task=task, mode=ctx.state.mode,
            retrieved_chunks=chunks, examples=examples, style_anchors=anchors,
            session_history=session_history,
        )

        # Shared primitive: model step (tools enabled)
        result = await ctx.model_step(
            system_blocks=system_blocks,
            tools=anthropic_tool_defs(scope),
            tier=_pick_tier(ctx),
            max_tokens=4096,
        )

        if result.stop_reason == "end_turn" and not result.tool_uses:
            ctx.state.final_text = result.text
            ctx.state.done = True
            ctx.checkpoint_or_raise()
            break

        # Record assistant turn
        ctx.state.messages.append({"role": "assistant", "content": result.raw_content})

        # Shared primitive: tool step (parallel, pre-tainted, consent-gated)
        tool_blocks = await ctx.tool_step(result.tool_uses)
        ctx.state.messages.append({"role": "user", "content": tool_blocks})
        ctx.checkpoint_or_raise()

    if not ctx.state.done:
        ctx.state.final_text = ctx.state.final_text or (
            "I hit the tool-call budget for this job without reaching a final "
            f"answer. Partial progress saved. Tool calls used: {ctx.state.tool_calls_count}."
        )
        ctx.state.done = True
    # Delivery happens in JobContext.finalize() — atomic with the DONE flip.


async def _load_scoped_context(scope: str, task: str):
    """Returns (chunks, examples, anchors, tainted).

    `tainted` is True when either retrieval surfaced a chunk from a tainted
    knowledge source. Caller (chat mode) is responsible for propagating to
    `JobContext.state.tainted` — the wrapper tool path goes through
    `_execute_one` taint detection, but this internal path does not.
    """
    if scope == "orchestrator":
        return [], [], [], False
    from ..modes.retrieval import retrieve_knowledge
    chunks_res = await retrieve_knowledge(scope=scope, query=task, top_k=8)
    anchors_res = await retrieve_knowledge(scope=scope, query=task, top_k=4, style_anchors_only=True)
    tainted = bool(chunks_res.get("tainted") or anchors_res.get("tainted"))
    return chunks_res.get("chunks", []), [], anchors_res.get("chunks", []), tainted


def _pick_tier(ctx: JobContext) -> ModelTier:
    """Pick the model tier for this turn.

    Priority (Hermes-inspired /model command — Pattern A steal #3):
      1. Job-level override (set by automation, one-off escalations)
      2. Thread-level override (set by /model <tier> in Discord)
      3. Default STRONG (Sonnet)
    """
    from ..memory import threads as threads_mod
    from ..memory.db import connect

    # 1. Job-level
    if ctx.job.mode and hasattr(ctx.job, "model_tier_override"):
        override = getattr(ctx.job, "model_tier_override", None)
        if override:
            try:
                return ModelTier(override)
            except ValueError:
                pass

    # 2. Thread-level
    if ctx.job.thread_id:
        conn = connect()
        try:
            t_override = threads_mod.get_model_tier_override(
                conn, thread_id=ctx.job.thread_id,
            )
        finally:
            conn.close()
        if t_override:
            try:
                return ModelTier(t_override)
            except ValueError:
                pass

    # 3. Default
    return ModelTier.STRONG


# Back-compat for existing JobRenewer imports
class JobRenewer:
    """Deprecated: heartbeating is now internal to JobContext. Retained for
    backwards-compat with worker code that still passes it."""
    def __init__(self, job_id: str, worker_id: str):
        self.job_id = job_id
        self.worker_id = worker_id
    def beat(self) -> None:  # no-op; heartbeat is a background task now
        pass
