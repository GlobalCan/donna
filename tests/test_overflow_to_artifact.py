"""Overflow-to-artifact delivery path (Slack adapter, v0.5.0+).

When a final answer exceeds the message-cap thresholds, `_post_update`
saves the FULL text as an artifact and posts a short preview + pointer
message instead of flooding Slack with multi-part `(N/M)` messages.

Two thresholds (Slack-tuned for Block Kit's 3000-char section limit;
the inline cap is 3500 with overflow at 4× for clean and 1× for
tainted):

- Clean (non-tainted) text:  up to ~14k chars inline, then overflow
- Tainted text:              up to ~3500 chars inline, then overflow

Security rationale for the tighter tainted cap: attacker-controlled
output (derived from fetch_url, PDF attachments, search snippets)
shouldn't take up rows of Slack scrollback. Materializing tainted text
at length also makes it harder to visually distinguish legitimate
operator conversation from injection content. By routing tainted
overflow through the artifact path, the raw content sits in
compartmentalized storage and requires an explicit `botctl
artifact-show` to view in full.

The artifact:
- Inherits `tainted` from the source, so subsequent reads propagate taint
- Is tagged `overflow` + `tainted` where applicable
- Named `overflow:<job_id>:<Nchars>` for audit
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from donna.adapter.slack_adapter import (
    _OVERFLOW_CLEAN_MAX,
    _OVERFLOW_TAINTED_MAX,
    DonnaSlackBot,
)
from donna.config import settings
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction


class _FakeClient:
    """Stand-in for the Slack AsyncWebClient. Records every
    chat_postMessage call so tests can assert what got sent."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.chat_postMessage = AsyncMock(side_effect=self._track)

    async def _track(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "ts": "1.0"}


def _make_job() -> str:
    conn = connect()
    try:
        with transaction(conn):
            return jobs_mod.insert_job(conn, task="test")
    finally:
        conn.close()


def _bot_with_client(client: _FakeClient) -> DonnaSlackBot:
    """Build a DonnaSlackBot without instantiating slack_bolt's AsyncApp
    (which would try to connect). Just need the method machinery."""
    bot = DonnaSlackBot.__new__(DonnaSlackBot)
    bot.client = client  # type: ignore[attr-defined]
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
    client = _FakeClient()
    bot = _bot_with_client(client)

    short = "a perfectly normal grounded reply"
    ok = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=short, tainted=False,
    )
    assert ok is True
    assert len(client.calls) == 1
    assert short in client.calls[0]["text"]
    assert "(1/" not in client.calls[0]["text"]
    assert _artifacts() == []


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_short_tainted_text_stays_inline_no_artifact() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    client = _FakeClient()
    bot = _bot_with_client(client)

    short = "a brief tainted reply (eg a URL fetch summary)"
    ok = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=short, tainted=True,
    )
    assert ok is True
    assert len(client.calls) == 1
    assert "🔮" in client.calls[0]["text"]
    # Unfurls disabled for tainted
    assert client.calls[0].get("unfurl_links") is False
    assert client.calls[0].get("unfurl_media") is False
    assert _artifacts() == []


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_medium_clean_text_uses_multi_part_not_overflow() -> None:
    """Mid-sized clean text should multi-part, NOT overflow."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    client = _FakeClient()
    bot = _bot_with_client(client)

    # ~7000 chars — past one Slack section, but well below clean overflow cap
    medium = ("sentence. " * 700).strip()
    assert len(medium) < _OVERFLOW_CLEAN_MAX
    ok = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=medium, tainted=False,
    )
    assert ok is True

    assert len(client.calls) >= 2
    assert any("(1/" in c["text"] for c in client.calls)
    assert _artifacts() == []


# ---------- clean overflow -> artifact ------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_long_clean_text_goes_to_artifact() -> None:
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    client = _FakeClient()
    bot = _bot_with_client(client)

    # Past the clean cap (_OVERFLOW_CLEAN_MAX ≈ 14k)
    long = "Important content. " * 1000   # ~19k chars
    assert len(long) > _OVERFLOW_CLEAN_MAX
    ok = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=long, tainted=False,
    )
    assert ok is True
    assert len(client.calls) == 1
    pointer = client.calls[0]["text"]
    assert "📎" in pointer
    assert "Answer too long" in pointer or "saved as artifact" in pointer
    assert "botctl artifact-show" in pointer
    assert "(1/" not in pointer

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
    """A 5000-char tainted reply is INLINE for clean content but OVERFLOW
    for tainted. Don't let attacker content splash across multiple Slack
    messages when it could be one short pointer."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    client = _FakeClient()
    bot = _bot_with_client(client)

    tainted_medium = "Attacker sentence. " * 300    # ~5700 chars
    assert len(tainted_medium) > _OVERFLOW_TAINTED_MAX
    assert len(tainted_medium) < _OVERFLOW_CLEAN_MAX

    ok = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=tainted_medium, tainted=True,
    )
    assert ok is True
    assert len(client.calls) == 1
    pointer = client.calls[0]["text"]
    assert "🔮" in pointer
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
    client = _FakeClient()
    bot = _bot_with_client(client)

    tainted_long = "Attacker's extended content. " * 800    # ~22k
    ok = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=tainted_long, tainted=True,
    )
    assert ok is True
    assert len(client.calls) == 1
    assert "(1/" not in client.calls[0]["text"]
    arts = _artifacts()
    assert len(arts) == 1
    assert arts[0]["tainted"] == 1


# ---------- preview content ----------------------------------------


@pytest.mark.usefixtures("fresh_db")
@pytest.mark.asyncio
async def test_overflow_pointer_includes_leading_preview() -> None:
    """The pointer message shows the first ~1500 chars as preview so the
    operator has immediate context — don't force a botctl trip for the
    gist of the answer."""
    settings().artifacts_dir.mkdir(parents=True, exist_ok=True)
    jid = _make_job()
    client = _FakeClient()
    bot = _bot_with_client(client)

    marker = "UNIQUE_PREVIEW_MARKER"
    body = marker + ". " + ("continuing content. " * 1000)
    await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=body, tainted=False,
    )
    assert len(client.calls) == 1
    assert marker in client.calls[0]["text"]


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
    client = _FakeClient()
    bot = _bot_with_client(client)

    from donna.memory import artifacts as artifacts_mod

    def _blow_up(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(artifacts_mod, "save_artifact", _blow_up)

    body = "unique content " * 1500  # well past clean cap
    result = await bot._post_update(
        channel="C_test", job_id=jid, thread_ts=None,
        text=body, tainted=False,
    )
    assert result is False
    # The fallback "artifact save failed" stub is sent inline.
    assert len(client.calls) == 1
    assert "artifact save failed" in client.calls[0]["text"].lower()
    assert _artifacts() == []
