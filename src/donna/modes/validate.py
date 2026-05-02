"""Validate mode (v0.7.1) — URL-bounded grounded critique.

Codex 2026-05-02 review on the overnight plan framed the design:

- Single URL only for MVP. No multi-URL.
- Sanitization paraphrases — it would break verbatim quoted_span
  citations. Use the RAW (markdownified) content as the citation
  substrate, not the sanitized summary.
- Wrap raw chunks as untrusted content in the prompt; final output
  must include quoted_spans the validator can verify.
- Output is tainted (URL content drives it).
- Don't persist into the normal corpus — chunks are ephemeral
  (in-memory for this job; not written to knowledge_chunks).

The handler reuses the `GROUNDED_RESPONSE_SCHEMA` JSON shape and
`validate_grounded` validator. Difference vs. grounded mode: chunks
come from a single URL fetch instead of the scope's corpus.

Job task format:
  Plain URL only:
    "https://example.com/article"

  URL + claim to evaluate:
    "https://example.com/article\n---\nclaim: <text>"

The slash command (/donna_validate) constructs this format; manual
botctl callers can do the same.
"""
from __future__ import annotations

from typing import Any

import httpx
from markdownify import markdownify

from ..agent.compose import compose_system
from ..agent.context import JobContext
from ..ingest.chunk import chunk_text
from ..logging import get_logger
from ..memory import artifacts as artifacts_mod
from ..memory.db import connect
from ..modes.grounded import GROUNDED_RESPONSE_SCHEMA, _format_output
from ..observability import otel
from ..security.url_safety import UnsafeURL, assert_safe_url
from ..security.validator import validate_grounded
from ..types import Chunk, JobMode, ModelTier

log = get_logger(__name__)

_VALIDATE_FETCH_MAX_BYTES = 1_000_000   # 1MB cap; keeps prompt size sane
_VALIDATE_FETCH_TIMEOUT = 30.0
_VALIDATE_USER_AGENT = (
    "Donna/0.7 (+https://github.com/GlobalCan/donna; "
    "URL validation; solo-operator) httpx"
)


def _parse_validate_task(task: str) -> tuple[str, str | None]:
    """Pull (url, claim) out of the task string.

    Slash format: 'URL\\n---\\nclaim: <text>' or just 'URL'.
    """
    raw = task.strip()
    url, claim = raw, None
    if "\n---\n" in raw:
        url_part, _, rest = raw.partition("\n---\n")
        url = url_part.strip()
        for line in rest.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("claim:"):
                claim = stripped[len("claim:"):].strip()
                break
    elif raw.startswith("http://") or raw.startswith("https://"):
        # Tolerate "<url> <claim>" on one line.
        parts = raw.split(maxsplit=1)
        if len(parts) == 2 and parts[1]:
            url, claim = parts[0], parts[1]
    return url, claim


async def _ssrf_safe_fetch(url: str) -> tuple[str, str]:
    """Fetch URL with SSRF guards + content-type / size caps. Returns
    (raw_text, content_type)."""
    # Pre-flight SSRF check: scheme, blocklisted hostnames, immediate
    # IP literal, DNS resolution-based private IP detection.
    assert_safe_url(url)

    async with httpx.AsyncClient(  # noqa: SIM117
        timeout=_VALIDATE_FETCH_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": _VALIDATE_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            # Re-check the FINAL URL — redirects might have hopped from
            # public to internal. Codex's classic SSRF rebinding case.
            final_url = str(resp.url)
            if final_url != url:
                assert_safe_url(final_url)
            ctype = (resp.headers.get("content-type") or "")
            ctype = ctype.split(";", 1)[0].strip().lower()
            if not ctype:
                raise RuntimeError(
                    "missing_content_type — origin sent no Content-Type"
                )
            if not (ctype.startswith("text/")
                    or ctype.startswith("application/xhtml")
                    or ctype.startswith("application/xml")):
                raise RuntimeError(f"unsupported_content_type: {ctype}")
            declared_len = resp.headers.get("content-length")
            if (
                declared_len
                and declared_len.isdigit()
                and int(declared_len) > _VALIDATE_FETCH_MAX_BYTES
            ):
                raise RuntimeError(
                    "content_length_exceeds_cap: "
                    f"{declared_len} > {_VALIDATE_FETCH_MAX_BYTES}"
                )
            buf = bytearray()
            async for piece in resp.aiter_bytes():
                buf += piece
                if len(buf) > _VALIDATE_FETCH_MAX_BYTES:
                    break
            raw = bytes(buf[:_VALIDATE_FETCH_MAX_BYTES]).decode(
                "utf-8", errors="replace",
            )
    return raw, ctype


def _refusal(*, reason: str, badge: str = "⚠️") -> str:
    return f"[validate · refused] {badge} {reason}"


async def _do_validation(
    *, ctx: JobContext, chunks: list[Chunk], url: str,
    claim: str | None,
) -> None:
    """Run the actual model + validator pass against the URL chunks.

    Mirrors run_grounded's shape but seeds the user message with an
    explicit "evaluate this URL" instruction so the model knows it's
    not retrieving from a corpus.
    """
    # State the role and the data's untrusted nature plainly. Even
    # though chunks are passed via compose_system (which already wraps
    # them as untrusted), the user message reinforces the contract.
    user_question = (
        f"Evaluate the content fetched from `{url}`. "
        + (f"Specifically scrutinize this claim: \"{claim}\". " if claim else "")
        + "Identify the central claims, assess accuracy/clarity, and "
        "flag any obvious omissions, leaps, or unsupported assertions. "
        "EVERY claim in your response must include a quoted_span that "
        "is a verbatim substring (≥20 chars) from one of the cited "
        "chunks. Do not paraphrase quoted_span values."
    )

    system_blocks = compose_system(
        scope=ctx.job.agent_scope, task=user_question,
        mode=JobMode.GROUNDED, retrieved_chunks=chunks,
    )
    system_blocks[-1]["text"] += "\n\n" + GROUNDED_RESPONSE_SCHEMA

    with otel.span("validate.generate"):
        result = await ctx.model_step(
            system_blocks=system_blocks,
            messages=[{"role": "user", "content": user_question}],
            tier=ModelTier.STRONG,
            max_tokens=2048,
        )

    log.info(
        "validate.model_response",
        job_id=ctx.job.id, url=url[:200],
        preview=result.text[:300], length=len(result.text),
    )

    validation = validate_grounded(result.text, chunks)
    ctx.check_cancelled()

    if not validation.ok:
        issue_summary = "; ".join(
            f"{i.reason}: {i.claim[:80]}" for i in validation.issues[:5]
        )
        fixup = (
            f"Previous response failed citation validation. Issues: "
            f"{issue_summary}.\n\n"
            "Regenerate with strict verbatim quoted_spans. For each "
            "claim, the `quoted_span` field MUST be a LITERAL "
            "COPY-PASTE of characters from the cited chunk."
        )
        system_blocks[-1]["text"] += "\n\n" + fixup
        with otel.span("validate.regenerate"):
            result = await ctx.model_step(
                system_blocks=system_blocks,
                messages=[{"role": "user", "content": user_question}],
                tier=ModelTier.STRONG,
                max_tokens=2048,
            )
        validation = validate_grounded(result.text, chunks)

    ctx.state.final_text = _format_output(result.text, validation, chunks)
    ctx.state.done = True
    ctx.checkpoint_or_raise()


def _build_chunks_from_text(
    *, text: str, source_id: str, source_title: str,
) -> list[Chunk]:
    """Wrap chunk_text TextChunks in the dataclass the grounded
    validator expects. Synthetic IDs use the source_id prefix so each
    chunk's `id` is referenceable in the model's `citations`."""
    raw_chunks = chunk_text(text)
    chunks: list[Chunk] = []
    for c in raw_chunks:
        chunks.append(Chunk(
            id=f"{source_id}#{c.index}",
            source_id=source_id,
            agent_scope="validate_url",
            work_id=None,
            publication_date=None,
            source_type="url",
            content=c.content,
            score=1.0,
            chunk_index=c.index,
            is_style_anchor=False,
            source_title=source_title,
        ))
    return chunks


async def run_validate(ctx: JobContext) -> None:
    """Entry point invoked by agent.loop.run_job for JobMode.VALIDATE."""
    if ctx.state.done:
        return  # resume short-circuit

    url, claim = _parse_validate_task(ctx.job.task)

    # Hard refusal paths — operator gets a clear single-line reason.
    try:
        assert_safe_url(url)
    except UnsafeURL as e:
        ctx.state.final_text = _refusal(reason=f"unsafe URL: {e.reason}")
        ctx.state.done = True
        # Validate jobs always start tainted — no untrusted-content
        # exposure has happened yet, but the URL itself is operator
        # input we should treat as untrusted.
        ctx.state.tainted = True
        ctx.checkpoint_or_raise()
        return

    # Validate output is always tainted: the URL content drives the
    # critique, and even with the validator, model paraphrasing can
    # leak attacker phrasing.
    ctx.state.tainted = True
    otel.set_attr("agent.job.tainted", True)
    otel.set_attr("agent.taint.source_tool", "validate_url:fetch")

    ctx.check_cancelled()

    try:
        raw, ctype = await _ssrf_safe_fetch(url)
    except UnsafeURL as e:
        ctx.state.final_text = _refusal(
            reason=f"unsafe redirect destination: {e.reason}",
        )
        ctx.state.done = True
        ctx.checkpoint_or_raise()
        return
    except (httpx.HTTPError, RuntimeError) as e:
        ctx.state.final_text = _refusal(
            reason=f"fetch failed: {type(e).__name__}: {str(e)[:200]}",
        )
        ctx.state.done = True
        ctx.checkpoint_or_raise()
        return

    rendered = (
        markdownify(raw, heading_style="ATX")
        if ctype.startswith("text/html") else raw
    )

    # Save raw as a tainted artifact so the operator can recover the
    # exact source if they want to dig deeper. Tagged 'validate'
    # so retention or future audit can find them.
    conn = connect()
    try:
        art = artifacts_mod.save_artifact(
            conn, content=rendered,
            name=f"validate:{url}",
            mime="text/markdown" if ctype.startswith("text/html") else ctype,
            tags="validate,tainted",
            tainted=True,
            created_by_job=ctx.job.id,
        )
    finally:
        conn.close()

    chunks = _build_chunks_from_text(
        text=rendered, source_id=art["artifact_id"],
        source_title=url,
    )
    if not chunks:
        ctx.state.final_text = _refusal(
            reason="fetched content was empty after markdown rendering",
        )
        ctx.state.done = True
        ctx.checkpoint_or_raise()
        return

    ctx.state.artifact_refs.append(art["artifact_id"])

    log.info(
        "validate.fetched",
        job_id=ctx.job.id, url=url, content_type=ctype,
        chunk_count=len(chunks),
        artifact_id=art["artifact_id"],
    )

    await _do_validation(ctx=ctx, chunks=chunks, url=url, claim=claim)


# Public for tests + slash command pre-flight.
def parse_validate_task(task: str) -> tuple[str, str | None]:
    return _parse_validate_task(task)


__all__: tuple[str, ...] = (
    "run_validate",
    "parse_validate_task",
    "_VALIDATE_FETCH_MAX_BYTES",
    "_VALIDATE_FETCH_TIMEOUT",
)


# Optional accessors for tests
def _get_url_safety() -> Any:
    """Test hook — return the url_safety module for monkeypatching."""
    from ..security import url_safety
    return url_safety
