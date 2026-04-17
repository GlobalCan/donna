"""Debate orchestration — orchestrator wears hats.

One inference engine, sequentially adopting N scopes. Each turn retrieves from
its own scope only. When attacking, must quote prior-turn text.
"""
from __future__ import annotations

from typing import Any

from ..agent.compose import compose_system
from ..agent.model_adapter import model
from ..logging import get_logger
from ..observability import otel
from ..security.validator import validate_debate_turn
from ..types import JobMode, ModelTier
from .retrieval import retrieve_knowledge

log = get_logger(__name__)


async def run_debate(
    *,
    topic: str,
    scopes: list[str],
    rounds: int = 3,
    job_id: str | None = None,
) -> dict[str, Any]:
    if len(scopes) < 2 or len(scopes) > 4:
        return {"error": "debate requires 2–4 scopes"}
    rounds = max(1, min(rounds, 5))

    transcript: list[dict[str, Any]] = []
    issues_by_turn: list[dict[str, Any]] = []

    for r in range(rounds):
        for scope in scopes:
            # Build debate context (prior turns, all speakers)
            prior = "\n\n".join(
                f"**{t['scope']} (round {t['round']}):**\n{t['content']}"
                for t in transcript
            )
            # Retrieve strictly from this scope
            retr = await retrieve_knowledge(scope=scope, query=topic, top_k=6)
            chunks = retr.get("chunks", [])

            system_blocks = compose_system(
                scope=scope,
                task=topic,
                mode=JobMode.DEBATE,
                retrieved_chunks=chunks,
                debate_context=prior if prior else None,
            )

            user_msg = (
                f"Topic: {topic}\n\n"
                f"You are speaking as {scope} in round {r+1} of {rounds}.\n"
                "Draw only on your own corpus. If attacking another speaker's "
                "claim, quote their exact prior text."
            )

            with otel.span("debate.turn", **{
                "debate.scope": scope, "debate.round": r + 1, "agent.job.id": job_id,
            }):
                result = await model().generate(
                    system=system_blocks,
                    messages=[{"role": "user", "content": user_msg}],
                    tier=ModelTier.STRONG,
                    job_id=job_id,
                    max_tokens=1200,
                )

            issues = validate_debate_turn(result.text, transcript, scope)
            if issues:
                issues_by_turn.append({
                    "scope": scope, "round": r + 1, "issues": issues,
                })

            transcript.append({
                "round": r + 1,
                "scope": scope,
                "content": result.text,
                "chunks_cited": [c.id for c in chunks],
            })

    # Neutral summary in orchestrator scope
    summary_prompt = (
        "You are a neutral moderator summarizing a debate between "
        f"{' and '.join(scopes)} on the topic: {topic}.\n\n"
        "Requirements:\n"
        " - Identify actual agreements between speakers (if any)\n"
        " - Identify 3-5 concrete points of disagreement\n"
        " - State the strongest argument from each side\n"
        " - Do NOT assert anything as fact that wasn't stated in the debate\n"
        " - Keep it under 400 words\n"
    )
    debate_text = "\n\n".join(
        f"### {t['scope']} (round {t['round']})\n{t['content']}"
        for t in transcript
    )
    with otel.span("debate.summary"):
        summary_result = await model().generate(
            system=summary_prompt,
            messages=[{"role": "user", "content": debate_text}],
            tier=ModelTier.STRONG,
            job_id=job_id,
            max_tokens=1000,
        )

    return {
        "mode": "debate",
        "topic": topic,
        "scopes": scopes,
        "rounds": rounds,
        "transcript": transcript,
        "summary": summary_result.text,
        "issues": issues_by_turn,
    }
