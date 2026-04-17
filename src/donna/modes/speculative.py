"""Speculative mode — extrapolate from a scope's voice/patterns, clearly labeled.

Never asserts actual views. Uses retrieved chunks as style/worldview anchors
(not as claim support). Gated by per-scope `allow_speculation` policy.
"""
from __future__ import annotations

from typing import Any

from ..agent.compose import compose_system
from ..agent.model_adapter import model
from ..logging import get_logger
from ..memory import prompts as prompts_mod
from ..memory.db import connect
from ..observability import otel
from ..types import JobMode, ModelTier
from .retrieval import retrieve_knowledge

log = get_logger(__name__)


async def answer_speculative(
    scope: str, question: str, *, job_id: str | None = None,
) -> dict[str, Any]:
    # Policy check
    conn = connect()
    try:
        prompt_row = prompts_mod.active_prompt(conn, scope)
    finally:
        conn.close()
    if not prompt_row or not prompt_row.get("speculation_allowed"):
        return {
            "mode": "speculative",
            "refused": True,
            "reason": (
                f"Speculation is disabled for scope '{scope}'. "
                "Enable it per-scope via agent_prompts.speculation_allowed = 1."
            ),
        }

    # Retrieve style anchors + general context
    anchors_res = await retrieve_knowledge(
        scope=scope, query=question, top_k=5, style_anchors_only=True,
    )
    ctx_res = await retrieve_knowledge(scope=scope, query=question, top_k=8)

    system_blocks = compose_system(
        scope=scope,
        task=question,
        mode=JobMode.SPECULATIVE,
        retrieved_chunks=ctx_res.get("chunks", []),
        style_anchors=anchors_res.get("chunks", []),
    )

    with otel.span("speculative.generate", **{"agent.scope": scope}):
        result = await model().generate(
            system=system_blocks,
            messages=[{"role": "user", "content": question}],
            tier=ModelTier.STRONG,
            job_id=job_id,
            max_tokens=2048,
        )

    # Post-check: ban assertion phrasings. If found, add a label rather than rejecting.
    banned_patterns = ["thinks that", "says that", "believes that", "argues that"]
    flags = [p for p in banned_patterns if p in result.text.lower()]

    return {
        "mode": "speculative",
        "scope": scope,
        "label": f"🔮 SPECULATIVE — extrapolated from {scope}'s documented patterns, not their actual view",
        "text": result.text,
        "flagged_phrasings": flags,
        "calibration": sorted({
            c.source_title or c.source_id
            for c in (ctx_res.get("chunks", []) + anchors_res.get("chunks", []))
        }),
    }
