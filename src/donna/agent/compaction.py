"""Context compaction — triggered every N tool calls.

Replaces the tail of the message list with a Haiku-generated summary +
references to artifacts where full output is preserved.
"""
from __future__ import annotations

import json
from typing import Any

from ..logging import get_logger
from ..observability import otel
from ..types import ModelTier
from .model_adapter import model

log = get_logger(__name__)


COMPACT_SYSTEM = (
    "You are compacting the tool-call history of an AI assistant's ongoing job. "
    "Produce a single concise summary (≤ 500 tokens) that preserves:\n"
    " - Facts learned (what questions were answered)\n"
    " - URLs visited (with their topic)\n"
    " - Artifacts created (with their IDs and purpose)\n"
    " - Decisions made\n"
    " - Outstanding open questions\n"
    "Drop: raw tool outputs, exploratory dead ends, repetitive content.\n"
    "Output only the summary, no preamble."
)


async def compact_messages(
    messages: list[dict[str, Any]], artifact_refs: list[str]
) -> list[dict[str, Any]]:
    """Summarize all messages after the first (initial user task) and replace them
    with a single compacted `user` message."""
    if len(messages) <= 3:
        return messages

    initial = messages[0]  # first user task
    to_compact = messages[1:]

    tail_text = json.dumps(to_compact, default=str)[:40_000]

    with otel.span("agent.compact", **{"compact.input_chars": len(tail_text)}):
        result = await model().generate(
            system=COMPACT_SYSTEM,
            messages=[{"role": "user", "content": tail_text}],
            tier=ModelTier.FAST,
            max_tokens=1200,
        )
    summary = result.text

    art_ref_line = ""
    if artifact_refs:
        art_ref_line = f"\n\nArtifacts available (use read_artifact): {', '.join(artifact_refs[-20:])}"

    compacted = {
        "role": "user",
        "content": (
            f"[CONTEXT COMPACTED — {len(to_compact)} prior messages replaced]\n"
            f"{summary}{art_ref_line}"
        ),
    }
    log.info("agent.compact.done", replaced=len(to_compact), summary_len=len(summary))
    return [initial, compacted]
