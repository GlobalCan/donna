"""Grounded mode — strict-citation Q&A over a scope's corpus.

Used when the user asks a scope (e.g. author_lewis) a question and wants only
answers that can be cited to retrieved chunks. If retrieval returns nothing
above threshold, the mode refuses rather than generating.
"""
from __future__ import annotations

from typing import Any

from ..agent.compose import compose_system
from ..agent.model_adapter import model
from ..logging import get_logger
from ..observability import otel
from ..security.validator import validate_grounded
from ..types import JobMode, ModelTier
from .retrieval import retrieve_knowledge

log = get_logger(__name__)


GROUNDED_RESPONSE_SCHEMA = """
Respond with valid JSON matching this schema:
{
  "claims": [
    {"text": "<natural-language claim>", "citations": ["<chunk_id>", ...]},
    ...
  ],
  "prose": "<stitched-together natural-language answer with [#chunk_id] markers inline>"
}
Every claim MUST cite at least one chunk id (without the '#' prefix) from the
retrieved context. Prose is the human-readable reply; claims are machine-verifiable.
Output ONLY the JSON object. No preamble, no code fences.
"""


async def answer_grounded(
    scope: str, question: str, *, job_id: str | None = None,
) -> dict[str, Any]:
    retrieval = await retrieve_knowledge(scope=scope, query=question, top_k=8)
    chunks = retrieval.get("chunks", [])

    if not chunks:
        return {
            "mode": "grounded",
            "refused": True,
            "reason": f"I don't have material from {scope} on this topic.",
        }

    system_blocks = compose_system(
        scope=scope, task=question, mode=JobMode.GROUNDED,
        retrieved_chunks=chunks,
    )
    # Extend the final (task) block with the response schema
    system_blocks[-1]["text"] += "\n\n" + GROUNDED_RESPONSE_SCHEMA

    with otel.span("grounded.generate", **{"agent.scope": scope}):
        result = await model().generate(
            system=system_blocks,
            messages=[{"role": "user", "content": question}],
            tier=ModelTier.STRONG,
            job_id=job_id,
            max_tokens=2048,
        )

    validation = validate_grounded(result.text, chunks)

    if not validation.ok:
        # One-shot retry with stricter instruction
        fixup_prompt = (
            "Previous response failed citation validation. Issues: "
            + "; ".join(f"{i.reason}: {i.claim[:80]}" for i in validation.issues[:5])
            + "\nRegenerate. Every claim must cite a valid chunk id from the "
            "retrieved context. If you cannot support a claim, omit it."
        )
        system_blocks[-1]["text"] += "\n\n" + fixup_prompt
        with otel.span("grounded.regenerate", **{"agent.scope": scope}):
            result = await model().generate(
                system=system_blocks,
                messages=[{"role": "user", "content": question}],
                tier=ModelTier.STRONG,
                job_id=job_id,
                max_tokens=2048,
            )
        validation = validate_grounded(result.text, chunks)

    return {
        "mode": "grounded",
        "scope": scope,
        "raw": result.text,
        "validated": validation.ok,
        "issues": [
            {"claim": i.claim[:200], "reason": i.reason} for i in validation.issues
        ],
        "chunks_used": [c.id for c in chunks],
        "sources": sorted({c.source_title or c.source_id for c in chunks}),
    }
