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
from ..tools.registry import anthropic_tool_defs
from ..types import JobMode, ModelTier
from .compose import compose_system
from .context import JobContext, LeaseLost

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
        else:  # CHAT and default
            await _run_chat(ctx)


async def _run_chat(ctx: JobContext) -> None:
    """Chat / agent-loop mode: iterate LLM ↔ tools until end_turn or budget."""
    s = settings()
    max_tool_calls = s.max_tool_calls_per_job
    scope = ctx.job.agent_scope
    task = ctx.job.task

    while not ctx.state.done and ctx.state.tool_calls_count < max_tool_calls:
        # Shared primitive: compaction
        await ctx.maybe_compact()

        # Shared primitive: retrieval (if scope has a corpus)
        chunks, examples, anchors = await _load_scoped_context(scope, task)

        # Shared primitive: compose
        system_blocks = compose_system(
            scope=scope, task=task, mode=ctx.state.mode,
            retrieved_chunks=chunks, examples=examples, style_anchors=anchors,
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


async def _load_scoped_context(scope: str, task: str):
    if scope == "orchestrator":
        return [], [], []
    from ..modes.retrieval import retrieve_knowledge
    chunks_res = await retrieve_knowledge(scope=scope, query=task, top_k=8)
    anchors_res = await retrieve_knowledge(scope=scope, query=task, top_k=4, style_anchors_only=True)
    return chunks_res.get("chunks", []), [], anchors_res.get("chunks", [])


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
