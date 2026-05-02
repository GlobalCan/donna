"""V0.7.1: validate mode handler — task parsing, chunk wrapping, refusal paths.

End-to-end run_validate with real httpx + real model is exercised by
the operator running `/donna_validate` against a real URL. These tests
lock in the deterministic, offline-testable surfaces:

- task parsing (url + optional claim)
- chunk wrapping (TextChunks → Chunk dataclass with synthetic ids)
- refusal paths (unsafe URL → run_validate returns a refusal final_text
  without making any network call)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from donna.modes.validate import (
    _build_chunks_from_text,
    parse_validate_task,
    run_validate,
)
from donna.types import Chunk, JobMode

# ---------- task parsing ---------------------------------------------------


def test_parse_url_only() -> None:
    url, claim = parse_validate_task("https://example.com/article")
    assert url == "https://example.com/article"
    assert claim is None


def test_parse_url_plus_claim_separator_format() -> None:
    """The slash command's preferred format: `URL\\n---\\nclaim: <text>`."""
    task = "https://example.com/article\n---\nclaim: this article is wrong about X"
    url, claim = parse_validate_task(task)
    assert url == "https://example.com/article"
    assert claim == "this article is wrong about X"


def test_parse_url_plus_claim_space_format() -> None:
    """Tolerant of `URL <claim>` on one line for direct CLI calls."""
    url, claim = parse_validate_task(
        "https://example.com/article some claim text"
    )
    assert url == "https://example.com/article"
    assert claim == "some claim text"


def test_parse_strips_whitespace() -> None:
    url, claim = parse_validate_task("   https://example.com/  ")
    assert url == "https://example.com/"
    assert claim is None


# ---------- chunk wrapping -------------------------------------------------


def test_build_chunks_wraps_with_synthetic_ids() -> None:
    """Each TextChunk gets wrapped in a Chunk with a deterministic id
    of the form `<source_id>#<index>`. The validator uses these ids
    when checking citations, so they must be referenceable from the
    model's response."""
    text = "para1 line 1.\n\npara2 line 2.\n\npara3 line 3.\n\n" * 50
    chunks = _build_chunks_from_text(
        text=text, source_id="art_xxx", source_title="https://x/y",
    )
    assert len(chunks) > 0
    assert all(isinstance(c, Chunk) for c in chunks)
    assert all(c.id.startswith("art_xxx#") for c in chunks)
    assert chunks[0].source_title == "https://x/y"
    assert chunks[0].source_type == "url"
    assert chunks[0].agent_scope == "validate_url"


def test_build_chunks_empty_text_returns_empty() -> None:
    chunks = _build_chunks_from_text(
        text="", source_id="art_xxx", source_title="https://x",
    )
    assert chunks == []


# ---------- refusal paths in run_validate ----------------------------------


def _build_ctx_for_validate(task: str):
    """Construct a minimal JobContext-like object that run_validate's
    refusal path can write to without needing a real DB or worker."""
    from datetime import UTC, datetime

    from donna.types import Job, JobState, JobStatus

    job = Job(
        id="job_test", agent_scope="validate_url",
        task=task, mode=JobMode.VALIDATE,
        status=JobStatus.RUNNING, thread_id=None, priority=5,
        owner="w_test",
        lease_until=datetime(2030, 1, 1, tzinfo=UTC),
        checkpoint_state=None, tainted=False,
        cost_usd=0.0, tool_call_count=0,
        created_at=datetime(2026, 5, 2, tzinfo=UTC),
        started_at=None, finished_at=None, error=None,
    )
    state = JobState(
        job_id="job_test", agent_scope="validate_url",
        mode=JobMode.VALIDATE,
    )
    ctx = MagicMock()
    ctx.job = job
    ctx.state = state
    ctx.check_cancelled = MagicMock()
    ctx.checkpoint_or_raise = MagicMock()
    ctx.model_step = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_run_validate_refuses_localhost_url() -> None:
    """Sanity check the refusal path: localhost URL must produce a
    refusal final_text, set done=True, and never call model_step."""
    ctx = _build_ctx_for_validate("http://localhost:9000/admin")

    await run_validate(ctx)

    assert ctx.state.done is True
    assert ctx.state.final_text is not None
    assert "[validate · refused]" in ctx.state.final_text
    assert "unsafe URL" in ctx.state.final_text
    ctx.model_step.assert_not_awaited()
    # Validate jobs always end up tainted, even on refusal — the URL
    # is operator input that's been touched.
    assert ctx.state.tainted is True


@pytest.mark.asyncio
async def test_run_validate_refuses_metadata_ip() -> None:
    ctx = _build_ctx_for_validate(
        "http://169.254.169.254/latest/meta-data/"
    )
    await run_validate(ctx)
    assert "[validate · refused]" in ctx.state.final_text
    assert ctx.state.done is True


@pytest.mark.asyncio
async def test_run_validate_refuses_disallowed_scheme() -> None:
    ctx = _build_ctx_for_validate("file:///etc/passwd")
    await run_validate(ctx)
    assert "[validate · refused]" in ctx.state.final_text
    assert ctx.state.done is True


@pytest.mark.asyncio
async def test_run_validate_resume_short_circuit() -> None:
    """If state.done is already True (resume after a worker crash that
    completed validation but lost the lease before finalize), don't
    re-run — that would waste model spend and potentially overwrite
    final_text."""
    ctx = _build_ctx_for_validate("https://example.com/")
    ctx.state.done = True
    ctx.state.final_text = "previous output preserved"

    await run_validate(ctx)

    assert ctx.state.final_text == "previous output preserved"
    ctx.model_step.assert_not_awaited()
    ctx.checkpoint_or_raise.assert_not_called()
