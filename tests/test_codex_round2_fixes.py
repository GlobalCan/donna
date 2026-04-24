"""Codex round-2 follow-up fixes — tests for specific regressions.

Each test binds to the real code path the fix lives in, not to a reimplemented
copy of the coercion logic. All five tests MUST fail on the pre-fix code.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction
from donna.security.consent import _persist_pending
from donna.security.validator import _has_substring_overlap
from donna.tools import attachments as attachments_mod
from donna.tools import web as web_mod
from donna.types import JobMode, JobStatus

# ---------- #1: fetch_url was fail-open on missing Content-Type -------------


class _FakeStreamResponse:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chunks = chunks
        self.headers: dict[str, str] = dict(headers) if headers else {}

    async def __aenter__(self) -> _FakeStreamResponse:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self):
        for c in self._chunks:
            yield c


def _patched_client(stream_response: _FakeStreamResponse) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.stream = MagicMock(return_value=stream_response)
    return client


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_fetch_url_refuses_when_content_type_header_is_absent() -> None:
    # Server sends NO Content-Type header at all. Pre-fix, our
    # `if ctype and not any(...)` short-circuited on empty ctype and
    # treated the response as textual. Now must return missing_content_type.
    fake = _FakeStreamResponse([b"opaque bytes"], headers={})  # no content-type
    with patch.object(web_mod.httpx, "AsyncClient", return_value=_patched_client(fake)):
        out = await web_mod.fetch_url(url="http://example.invalid/mystery")
    assert out.get("error") == "missing_content_type"


# ---------- #2: _persist_pending half-transition guarded on status ----------


def _seed_job_with_status(owner: str, status: JobStatus) -> str:
    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn, task="test", agent_scope="orchestrator", mode=JobMode.CHAT,
            )
        claimed = jobs_mod.claim_next_queued(conn, worker_id=owner)
        assert claimed is not None and claimed.id == jid
        # Force a non-'running' status (cancelled or paused)
        if status != JobStatus.RUNNING:
            with transaction(conn):
                conn.execute(
                    "UPDATE jobs SET status = ? WHERE id = ?",
                    (status.value, jid),
                )
    finally:
        conn.close()
    return jid


def _pending_count(jid: str) -> int:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM pending_consents WHERE job_id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    return int(row["n"])


@pytest.mark.usefixtures("fresh_db")
def test_persist_pending_refuses_when_job_already_cancelled() -> None:
    # Owner matches, but status is CANCELLED. Pre-fix, INSERT still fired
    # (UPDATE's WHERE status='running' silently no-op'd), leaving an orphan
    # pending_consents row. Now must return None with zero rows inserted.
    jid = _seed_job_with_status(owner="worker-A", status=JobStatus.CANCELLED)
    pid = _persist_pending(
        job_id=jid, tool_name="run_python", arguments={},
        tainted=False, worker_id="worker-A",
    )
    assert pid is None
    assert _pending_count(jid) == 0


@pytest.mark.usefixtures("fresh_db")
def test_persist_pending_refuses_when_job_already_paused() -> None:
    # Same class, different terminal status.
    jid = _seed_job_with_status(
        owner="worker-A", status=JobStatus.PAUSED_AWAITING_CONSENT,
    )
    pid = _persist_pending(
        job_id=jid, tool_name="run_python", arguments={},
        tainted=False, worker_id="worker-A",
    )
    assert pid is None
    assert _pending_count(jid) == 0


# ---------- #4: tainted attachment persists through ingest ------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_tainted_flag_persists_through_ingest_text_into_sources() -> None:
    """Ingest with tainted=True must land tainted=1 on BOTH the source
    artifact and the knowledge_sources row. Without this, a Discord
    attachment's taint dies at the end of the ingesting job."""
    from donna.ingest.pipeline import ingest_text

    # Stub embed_documents so the test doesn't hit Voyage — return one
    # embedding per input chunk.
    async def _fake_embed(docs: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in docs]
    with patch("donna.ingest.pipeline.embed_documents", side_effect=_fake_embed):
        result = await ingest_text(
            scope="t_tainted",
            source_type="article",
            title="sketchy article",
            content="paragraph one\n\nparagraph two\n\nparagraph three\n\npara four",
            copyright_status="personal_use",
            tainted=True,
        )

    assert "source_id" in result
    src_id = result["source_id"]

    conn = connect()
    try:
        src_row = conn.execute(
            "SELECT tainted, source_ref FROM knowledge_sources WHERE id = ?", (src_id,),
        ).fetchone()
        assert src_row["tainted"] == 1, "knowledge_sources row missing taint flag"

        art_row = conn.execute(
            "SELECT tainted FROM artifacts WHERE id = ?",
            (src_row["source_ref"],),
        ).fetchone()
        assert art_row["tainted"] == 1, "source artifact missing taint flag"
    finally:
        conn.close()


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_ingest_discord_attachment_defaults_to_tainted() -> None:
    """End-to-end: ingest_discord_attachment of a small text file must
    result in a tainted=1 knowledge_sources row (Codex round-2 #4)."""
    payload = b"Line one about espresso.\n\nLine two about Seattle."
    fake = _FakeStreamResponse([payload], headers={"content-type": "text/plain"})

    async def _fake_embed(docs: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in docs]
    with (
        patch.object(attachments_mod.httpx, "AsyncClient", return_value=_patched_client(fake)),
        patch("donna.ingest.pipeline.embed_documents", side_effect=_fake_embed),
    ):
        result = await attachments_mod.ingest_discord_attachment(
            scope="t_discord",
            attachment_url="http://example.invalid/note.txt",
            title="A Discord note",
        )

    assert result.get("tainted") is True
    src_id = result["source_id"]

    conn = connect()
    try:
        row = conn.execute(
            "SELECT tainted FROM knowledge_sources WHERE id = ?", (src_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row["tainted"] == 1, "Discord attachment didn't persist taint"


# ---------- #8: _has_substring_overlap off-by-one at final window -----------


def test_substring_overlap_matches_at_final_window() -> None:
    # 15-char haystack; 15-char needle at offset 0 IS the whole string.
    # Pre-fix `range(len(b) - min_len)` == range(0) — loop never runs.
    # Fix: `+ 1` makes range(1), which runs once at i=0.
    needle = "abcdefghijklmno"
    assert _has_substring_overlap(needle, needle, min_len=15) is True


def test_substring_overlap_matches_when_pattern_is_at_end() -> None:
    # haystack of length 20, pattern of length 15 at offset 5 (the tail).
    # Pre-fix `range(20 - 15)` == range(5) — stops at i=4, misses i=5.
    # Fix: range(6), i=5 runs and finds the final-window match.
    haystack = "xxxxxabcdefghijklmno"  # last 15 chars are needle
    needle_in_a = "abcdefghijklmno"
    # a = the text we're scanning WITHIN, b = the text we're extracting
    # windows FROM. Build so that a window from b's tail is present in a.
    # Per function contract: `for i in range(len(b) - min_len + 1): sub = b[i:i+min_len]; if sub in a: return True`
    # Pick b = 20 chars, its tail-15 must be in a.
    assert _has_substring_overlap(needle_in_a, haystack, min_len=15) is True
