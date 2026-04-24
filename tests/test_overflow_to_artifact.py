"""Overflow-to-artifact delivery path.

When a final answer exceeds the message-cap thresholds, `_post_update`
saves the FULL text as an artifact and posts a short preview + pointer
message instead of flooding Discord with multi-part `(N/M)` messages.

Two thresholds:

- Clean (non-tainted) text:  up to 3 parts inline (~5700 chars), then overflow
- Tainted text:              up to 1 part inline (~1900 chars), then overflow

Security rationale for the tighter tainted cap: attacker-controlled output
(derived from fetch_url, PDF attachments, search snippets) shouldn't take
up rows of Discord scrollback. Materializing tainted text at length also
makes it harder to visually distinguish legitimate operator conversation
from injection content. By routing tainted overflow through the artifact
path, the raw content sits in compartmentalized storage and requires an
explicit `botctl artifact-show` to view in full.

The artifact:
- Inherits `tainted` from the source, so subsequent reads propagate taint
- Is tagged `overflow` + `tainted` where applicable
- Named `overflow:<job_id>:<Nchars>` for audit
- Is created via the same `save_artifact` call chain used by `save_artifact`
  tool, so schema and dedup (sha256 UNIQUE) are identical
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from donna.adapter.discord_adapter import (
    _OVERFLOW_CLEAN_MAX,
    _OVERFLOW_TAINTED_MAX,
    DonnaBot,
)
from donna.config import settings
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction


class _FakeChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.send = AsyncMock(side_effect=self._track)
        self.id = 42

    async def _track(self, content: str) -> object:
        self.sent.append(content)
        class _Msg:
            id = 1
        return _Msg()


def _make_job() -> str:
    conn = connect()
    try:
        with transaction(conn):
            return jobs_mod.insert_job(conn, task="test")
    finally:
        conn.close()


def _bot_with_channel(ch: _FakeChannel) -> DonnaBot:
    """Build a DonnaBot without running discord.Client.__init__ (which
    spins up a gateway connection). We just need the method machinery."""
    bot = DonnaBot.__new__(DonnaBot)

    async def _fake_resolve(job_id: str) -> _FakeChannel | None:
        return ch

    bot._resolve_channel_for_job = _fake_resolve  # type: ignore[attr-defined]
    return bot


def _artifacts() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, name, mime, tags, tainted, bytes FROM artifacts "
            "ORDER BY created_at"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


# ---------- short text stays inline ----------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_short_clean_text_stays_inline_no_artifact() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    short = "a perfectly normal grounded reply"
    ok = await bot._post_update(job_id=jid, text=short, tainted=False)
    assert ok is True

    # One inline message, no multi-part marker
    assert len(ch.sent) == 1
    assert short in ch.sent[0]
    assert "(1/" not in ch.sent[0]
    # No artifact was created
    assert _artifacts() == []


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_short_tainted_text_stays_inline_no_artifact() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    short = "a brief tainted reply (eg a URL fetch summary)"
    ok = await bot._post_update(job_id=jid, text=short, tainted=True)
    assert ok is True

    assert len(ch.sent) == 1
    assert "🔮" in ch.sent[0]
    assert _artifacts() == []


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_medium_clean_text_uses_multi_part_not_overflow() -> None:
    """Clean text in the 2000-5000 char range should multi-part, NOT
    overflow. Overflow cutoff is ~5700."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    # 3500 chars — expected 2 parts inline
    medium = ("sentence. " * 350).strip()
    assert len(medium) < _OVERFLOW_CLEAN_MAX
    ok = await bot._post_update(job_id=jid, text=medium, tainted=False)
    assert ok is True

    assert len(ch.sent) >= 2
    assert any("(1/" in m for m in ch.sent)
    assert _artifacts() == []


# ---------- clean overflow -> artifact ------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_long_clean_text_goes_to_artifact() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    # Well past the clean cap (_OVERFLOW_CLEAN_MAX ≈ 5700)
    long = "Important content. " * 600   # ~11k chars
    assert len(long) > _OVERFLOW_CLEAN_MAX
    ok = await bot._post_update(job_id=jid, text=long, tainted=False)
    assert ok is True

    # One short pointer message sent, not multi-part
    assert len(ch.sent) == 1
    pointer = ch.sent[0]
    assert "📎" in pointer
    assert "too long for DM" in pointer
    assert "botctl artifact-show" in pointer
    # Not flooded with (1/N) markers
    assert "(1/" not in pointer

    # Artifact with FULL content saved
    arts = _artifacts()
    assert len(arts) == 1
    assert arts[0]["name"].startswith(f"overflow:{jid}:")
    assert arts[0]["tainted"] == 0
    assert arts[0]["bytes"] == len(long.encode("utf-8"))
    assert "overflow" in arts[0]["tags"]


# ---------- tainted overflow -> artifact (tighter threshold) --------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_medium_tainted_text_overflows_because_tainted_cap_is_tighter() -> None:
    """A 2500-char tainted reply is INLINE for clean content but OVERFLOW
    for tainted. Security: don't let attacker content splash across 2-3
    Discord messages when it could be one short pointer."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    tainted_medium = "Attacker sentence. " * 180    # ~3400 chars
    assert len(tainted_medium) > _OVERFLOW_TAINTED_MAX
    assert len(tainted_medium) < _OVERFLOW_CLEAN_MAX

    ok = await bot._post_update(
        job_id=jid, text=tainted_medium, tainted=True,
    )
    assert ok is True

    assert len(ch.sent) == 1
    pointer = ch.sent[0]
    assert "🔮" in pointer  # tainted header keeps the signal marker
    assert "Tainted answer" in pointer or "compartmentalized" in pointer
    assert "untrusted" in pointer or "Review the artifact carefully" in pointer

    arts = _artifacts()
    assert len(arts) == 1
    assert arts[0]["tainted"] == 1, (
        "the overflow artifact MUST inherit taint from the message — "
        "otherwise a downstream read_artifact would see clean content"
    )
    assert "tainted" in arts[0]["tags"]


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_long_tainted_text_still_goes_to_artifact_not_multipart() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    tainted_long = "Attacker's extended content. " * 500    # ~14.5k
    ok = await bot._post_update(
        job_id=jid, text=tainted_long, tainted=True,
    )
    assert ok is True

    # Single pointer, not (1/N) multipart
    assert len(ch.sent) == 1
    assert "(1/" not in ch.sent[0]
    arts = _artifacts()
    assert len(arts) == 1
    assert arts[0]["tainted"] == 1


# ---------- preview content ----------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_overflow_pointer_includes_leading_preview() -> None:
    """The pointer message shows the first ~1200 chars as preview so the
    operator has immediate context — don't force a botctl trip for the
    gist of the answer."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    marker = "UNIQUE_PREVIEW_MARKER"
    body = marker + ". " + ("continuing content. " * 500)
    await bot._post_update(job_id=jid, text=body, tainted=False)

    assert len(ch.sent) == 1
    assert marker in ch.sent[0]


# ---------- failure path ------------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_artifact_save_failure_falls_back_to_truncated_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If save_artifact blows up (disk full, etc.), we must not drop the
    message entirely — operator at least sees a truncated stub. Graceful
    degradation."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    ch = _FakeChannel()
    bot = _bot_with_channel(ch)

    from donna.memory import artifacts as artifacts_mod

    def _blow_up(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(artifacts_mod, "save_artifact", _blow_up)

    body = "unique content " * 600  # well past clean cap
    result = await bot._post_update(job_id=jid, text=body, tainted=False)

    # Return False to signal the drainer to retry or log; but the fallback
    # inline send did happen so operator isn't in the dark
    assert result is False
    assert len(ch.sent) == 1
    assert "artifact save failed" in ch.sent[0].lower()
    # No artifact created
    assert _artifacts() == []


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_resolve_channel_failure_returns_false_no_artifact() -> None:
    """If the channel can't be resolved, no Discord write happens and no
    artifact is wasted either."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    bot = DonnaBot.__new__(DonnaBot)

    async def _no_channel(job_id: str) -> None:
        return None

    bot._resolve_channel_for_job = _no_channel  # type: ignore[attr-defined]

    result = await bot._post_update(
        job_id=jid, text="x" * 10_000, tainted=False,
    )
    assert result is False
    # No artifact created — we never got far enough to save it
    assert _artifacts() == []
