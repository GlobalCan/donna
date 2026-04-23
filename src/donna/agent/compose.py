"""Prompt composition — stable prefix (cacheable) + volatile suffix.

Returns a system prompt as a *list* of content blocks compatible with Anthropic's
prompt-caching API: the stable prefix is marked with cache_control so subsequent
calls rehit cache.
"""
from __future__ import annotations

from typing import Any

from ..memory import prompts as prompts_mod
from ..memory.db import connect
from ..types import Chunk, JobMode


def compose_system(
    *,
    scope: str,
    task: str,
    mode: JobMode,
    retrieved_chunks: list[Chunk] | None = None,
    examples: list[dict[str, Any]] | None = None,
    style_anchors: list[Chunk] | None = None,
    debate_context: str | None = None,
) -> list[dict[str, Any]]:
    """Returns system prompt as content blocks; first block has cache_control marker."""
    conn = connect()
    try:
        prompt_row = prompts_mod.active_prompt(conn, scope)
        heuristics = prompts_mod.active_heuristics(conn, scope)
    finally:
        conn.close()

    base_prompt = prompt_row["system_prompt"] if prompt_row else _fallback_prompt(scope)

    # === STABLE PREFIX ===
    stable_parts = [base_prompt]

    if heuristics:
        stable_parts.append("\n\n## Active heuristics\n")
        for h in heuristics:
            stable_parts.append(f"- {h}\n")

    mode_instructions = _mode_instructions(mode)
    if mode_instructions:
        stable_parts.append("\n\n## Mode\n" + mode_instructions)

    stable = "".join(stable_parts)

    blocks: list[dict[str, Any]] = [
        {"type": "text", "text": stable, "cache_control": {"type": "ephemeral"}}
    ]

    # === VOLATILE SUFFIX ===
    volatile: list[str] = []

    if examples:
        volatile.append("\n\n## Examples of good responses\n")
        for ex in examples[:3]:
            volatile.append(
                f"---\nQ: {ex['task_description']}\nA: {ex['good_response']}\n"
            )

    if style_anchors:
        volatile.append("\n\n## Voice / style anchors (calibrate prose, do NOT cite)\n")
        for ch in style_anchors[:5]:
            volatile.append(
                f"[style #{ch.id}] {ch.content[:800]}\n"
            )

    if retrieved_chunks:
        volatile.append("\n\n## Relevant context chunks (cite with [#chunkId])\n")
        for ch in retrieved_chunks:
            src_info = f" ({ch.source_title}, {ch.publication_date})" if ch.source_title else ""
            volatile.append(
                f"[#{ch.id}]{src_info}\n{ch.content}\n\n"
            )

    if debate_context:
        volatile.append("\n\n## Debate so far\n" + debate_context + "\n")

    if volatile:
        blocks.append({"type": "text", "text": "".join(volatile)})

    # Task framing (most volatile, always last)
    blocks.append({"type": "text", "text": f"\n\n## Current task\n{task}"})

    return blocks


def _mode_instructions(mode: JobMode) -> str:
    if mode == JobMode.GROUNDED:
        return (
            "GROUNDED mode. Every factual claim about the scope's corpus MUST cite one "
            "or more chunk IDs using the format [#chunk_id]. If no chunks clear the "
            "relevance bar for the question, refuse: 'I don't have material on this.'"
        )
    if mode == JobMode.SPECULATIVE:
        return (
            "SPECULATIVE mode. You are extrapolating from the scope's documented "
            "patterns — NOT asserting their actual views. Required framings: 'Based on "
            "X's documented patterns...', 'X might argue...', 'Given X's writings, they "
            "would likely...'. BANNED: 'X thinks', 'X says', 'X believes' as assertions. "
            "You must never present speculation as fact."
        )
    if mode == JobMode.DEBATE:
        return (
            "DEBATE mode. You are speaking AS this scope. Use only material retrieved "
            "from your own scope. When attacking an opposing speaker's claim, you MUST "
            "quote their prior-turn text directly. Do not impute views they haven't "
            "stated in this debate. Rebut arguments, not speakers."
        )
    return ""


def _fallback_prompt(scope: str) -> str:
    return f"You are Donna, a personal AI assistant. Active scope: {scope}."
