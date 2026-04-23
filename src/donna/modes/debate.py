"""Debate orchestration — orchestrator wears hats.

One inference engine, sequentially adopting N scopes. Each turn retrieves from
its own scope only. When attacking, must quote prior-turn text.
"""
from __future__ import annotations

import json
from typing import Any

from ..agent.compose import compose_system
from ..agent.context import JobContext
from ..agent.model_adapter import model
from ..logging import get_logger
from ..observability import otel
from ..security.validator import validate_debate_turn
from ..types import JobMode, ModelTier
from .retrieval import retrieve_knowledge

log = get_logger(__name__)


async def run_debate_in_context(ctx: JobContext) -> None:
    """Entry point invoked by agent.loop.run_job for JobMode.DEBATE.

    The task is a JSON payload: {"scope_a":..., "scope_b":..., "topic":..., "rounds":...}
    """
    try:
        payload = json.loads(ctx.job.task) if ctx.job.task.strip().startswith("{") else {}
    except json.JSONDecodeError:
        payload = {}

    scope_a = payload.get("scope_a", ctx.job.agent_scope)
    scope_b = payload.get("scope_b", "orchestrator")
    topic = payload.get("topic", ctx.job.task)
    rounds = int(payload.get("rounds", 3))
    scopes = [scope_a, scope_b]
    if "scope_c" in payload:
        scopes.append(payload["scope_c"])
    if "scope_d" in payload:
        scopes.append(payload["scope_d"])

    result = await _debate_core(ctx=ctx, topic=topic, scopes=scopes, rounds=rounds)
    ctx.state.final_text = _format_debate(result)
    ctx.state.done = True
    ctx.checkpoint_or_raise()


def _format_debate(result: dict) -> str:
    if "error" in result:
        return f"[debate · error] {result['error']}"
    lines = [f"**Debate: {' vs '.join(result['scopes'])} on {result['topic']}**\n"]
    for t in result["transcript"]:
        lines.append(f"\n### {t['scope']} — round {t['round']}\n{t['content']}")
    lines.append(f"\n---\n**Summary:**\n{result['summary']}")
    if result.get("issues"):
        lines.append("\n_Validator flagged: "
                     + ", ".join(f"{i['scope']}-r{i['round']}" for i in result["issues"]) + "_")
    return "\n".join(lines)


async def _debate_core(
    *,
    ctx: JobContext | None = None,
    topic: str,
    scopes: list[str],
    rounds: int,
) -> dict:
    """Shared implementation used by both run_debate_in_context (JobContext path)
    and the legacy run_debate (direct-call path)."""
    if len(scopes) < 2 or len(scopes) > 4:
        return {"error": "debate requires 2–4 scopes"}
    rounds = max(1, min(rounds, 5))

    transcript: list[dict[str, Any]] = []
    issues_by_turn: list[dict[str, Any]] = []

    for r in range(rounds):
        for scope in scopes:
            prior = "\n\n".join(
                f"**{t['scope']} (round {t['round']}):**\n{t['content']}"
                for t in transcript
            )
            retr = await retrieve_knowledge(scope=scope, query=topic, top_k=6)
            chunks = retr.get("chunks", [])

            system_blocks = compose_system(
                scope=scope, task=topic, mode=JobMode.DEBATE,
                retrieved_chunks=chunks,
                debate_context=prior if prior else None,
            )
            user_msg = (
                f"Topic: {topic}\n\n"
                f"You are speaking as {scope} in round {r+1} of {rounds}.\n"
                "Draw only on your own corpus. If attacking another speaker's "
                "claim, quote their exact prior text."
            )

            if ctx is not None:
                ctx.check_cancelled()
            with otel.span("debate.turn", **{
                "debate.scope": scope, "debate.round": r + 1,
                "agent.job.id": ctx.job.id if ctx else None,
            }):
                if ctx is not None:
                    result = await ctx.model_step(
                        system_blocks=system_blocks,
                        messages=[{"role": "user", "content": user_msg}],
                        tier=ModelTier.STRONG, max_tokens=1200,
                    )
                else:
                    result = await model().generate(
                        system=system_blocks,
                        messages=[{"role": "user", "content": user_msg}],
                        tier=ModelTier.STRONG, max_tokens=1200,
                    )

            issues = validate_debate_turn(result.text, transcript, scope)
            if issues:
                issues_by_turn.append({"scope": scope, "round": r + 1, "issues": issues})

            transcript.append({
                "round": r + 1, "scope": scope, "content": result.text,
                "chunks_cited": [c.id for c in chunks],
            })

    # Neutral summary
    debate_text = "\n\n".join(
        f"### {t['scope']} (round {t['round']})\n{t['content']}" for t in transcript
    )
    summary_prompt = (
        f"You are a neutral moderator summarizing a debate between "
        f"{' and '.join(scopes)} on: {topic}.\n\n"
        "Identify agreements, 3-5 concrete disagreements, and each side's "
        "strongest argument. Under 400 words. Do not assert anything not "
        "stated in the debate."
    )
    with otel.span("debate.summary"):
        if ctx is not None:
            summary_result = await ctx.model_step(
                system_blocks=[{"type": "text", "text": summary_prompt}],
                messages=[{"role": "user", "content": debate_text}],
                tier=ModelTier.STRONG, max_tokens=1000,
            )
        else:
            summary_result = await model().generate(
                system=summary_prompt,
                messages=[{"role": "user", "content": debate_text}],
                tier=ModelTier.STRONG, max_tokens=1000,
            )

    return {
        "mode": "debate", "topic": topic, "scopes": scopes, "rounds": rounds,
        "transcript": transcript, "summary": summary_result.text,
        "issues": issues_by_turn,
    }


# Legacy API retained for existing tests / evals — delegates to _debate_core
async def run_debate(
    *,
    topic: str,
    scopes: list[str],
    rounds: int = 3,
    job_id: str | None = None,
) -> dict[str, Any]:
    return await _debate_core(ctx=None, topic=topic, scopes=scopes, rounds=rounds)
