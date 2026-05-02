"""V50-8 (v0.5.2): dual-field memory tests — raw + safe_summary.

Validates the architectural split:
  - tainted assistant rows store raw `content` for audit
  - async sanitizer backfills `safe_summary`
  - `compose_system` prefers safe_summary (unwrapped continuity) and
    falls back to the v0.4.4 untrusted-source wrapper when safe_summary
    is NULL (legacy data, race window, or sanitize failure)
"""
from __future__ import annotations

import pytest

from donna.agent.compose import compose_system
from donna.memory import threads as threads_mod
from donna.memory.db import connect, transaction
from donna.types import JobMode


def _make_thread() -> str:
    conn = connect()
    try:
        with transaction(conn):
            return threads_mod.get_or_create_thread(
                conn, channel_id="C_test", thread_external_id=None,
                title="dm",
            )
    finally:
        conn.close()


def _insert(
    *, thread_id: str, role: str, content: str,
    tainted: bool = False, safe_summary: str | None = None,
) -> str:
    conn = connect()
    try:
        with transaction(conn):
            return threads_mod.insert_message(
                conn, thread_id=thread_id, role=role, content=content,
                tainted=tainted, safe_summary=safe_summary,
            )
    finally:
        conn.close()


def _read_row(message_id: str) -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, role, content, tainted, safe_summary "
            "FROM messages WHERE id = ?",
            (message_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else {}


# ---------- threads.update_safe_summary ----------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_update_safe_summary_writes_when_null() -> None:
    tid = _make_thread()
    mid = _insert(thread_id=tid, role="assistant", content="raw web summary",
                  tainted=True)
    conn = connect()
    try:
        with transaction(conn):
            wrote = threads_mod.update_safe_summary(
                conn, message_id=mid, summary="Wikipedia said X about Y.",
            )
    finally:
        conn.close()
    assert wrote is True
    row = _read_row(mid)
    assert row["safe_summary"] == "Wikipedia said X about Y."
    # Raw audit column is preserved
    assert row["content"] == "raw web summary"


@pytest.mark.usefixtures("fresh_db")
def test_update_safe_summary_is_idempotent_via_null_guard() -> None:
    """Concurrent backfill attempts shouldn't overwrite each other.
    The WHERE safe_summary IS NULL guard makes the update no-op the
    second time."""
    tid = _make_thread()
    mid = _insert(thread_id=tid, role="assistant", content="raw",
                  tainted=True)
    conn = connect()
    try:
        with transaction(conn):
            first = threads_mod.update_safe_summary(
                conn, message_id=mid, summary="first",
            )
        with transaction(conn):
            second = threads_mod.update_safe_summary(
                conn, message_id=mid, summary="second",
            )
    finally:
        conn.close()
    assert first is True
    assert second is False
    assert _read_row(mid)["safe_summary"] == "first"


@pytest.mark.usefixtures("fresh_db")
def test_recent_messages_returns_safe_summary_field() -> None:
    """Read path exposes safe_summary so compose_system can route on it."""
    tid = _make_thread()
    _insert(thread_id=tid, role="user", content="ask")
    _insert(
        thread_id=tid, role="assistant", content="raw bytes",
        tainted=True, safe_summary="laundered paraphrase",
    )
    conn = connect()
    try:
        rows = threads_mod.recent_messages(conn, tid, limit=10)
    finally:
        conn.close()
    assert len(rows) == 2
    asst = rows[1]
    assert asst["role"] == "assistant"
    assert asst["tainted"] is True
    assert asst["safe_summary"] == "laundered paraphrase"


# ---------- compose_system rendering switch -----------------------------


def _compose_with_history(history: list[dict]) -> str:
    """Render a full system prompt and return the volatile section text."""
    blocks = compose_system(
        scope="orchestrator",
        task="follow-up question",
        mode=JobMode.CHAT,
        session_history=history,
    )
    # The session-history rendering goes into the volatile (last) block.
    return "\n".join(b.get("text", "") for b in blocks)


@pytest.mark.usefixtures("fresh_db")
def test_compose_renders_sanitized_tainted_unwrapped() -> None:
    """V50-8: tainted rows WITH safe_summary render as User/You dialogue,
    NOT inside the <untrusted_session_history> wrapper. The sanitize step
    is the trust boundary; the wrapper isn't needed once content is
    laundered."""
    history = [
        {
            "role": "user", "content": "what's the weather in Ottawa",
            "tainted": True, "safe_summary": "What is the weather in Ottawa?",
        },
        {
            "role": "assistant",
            "content": "raw web fetch with potentially adversarial tokens",
            "tainted": True,
            "safe_summary": "Ottawa was 7C and clear.",
        },
    ]
    out = _compose_with_history(history)

    # Sanitized tainted rendered as dialogue, NOT in wrapper
    assert "Ottawa was 7C and clear." in out
    assert "<untrusted_session_history>" not in out
    # The raw bytes never reach the rendered prompt
    assert "raw web fetch" not in out
    assert "potentially adversarial tokens" not in out


@pytest.mark.usefixtures("fresh_db")
def test_compose_falls_back_to_wrapper_for_null_safe_summary() -> None:
    """Legacy data and the race window between insert and backfill
    completion: tainted rows WITHOUT safe_summary render inside the
    v0.4.4 untrusted-source wrapper. Trust boundary preserved."""
    history = [
        {
            "role": "assistant",
            "content": "legacy raw bytes from pre-v0.5.2",
            "tainted": True,
            "safe_summary": None,
        },
    ]
    out = _compose_with_history(history)

    assert "<untrusted_session_history>" in out
    assert "legacy raw bytes" in out
    assert "DO" in out.upper() and "INSTRUCT" in out.upper()  # warning present


@pytest.mark.usefixtures("fresh_db")
def test_compose_mixes_sanitized_and_raw_correctly() -> None:
    """Both buckets coexist: sanitized rows in continuity dialogue,
    raw_only rows in the wrapper. No raw bytes leak into the
    continuity section."""
    history = [
        {
            "role": "assistant", "content": "DANGEROUS_RAW_1",
            "tainted": True, "safe_summary": "Safe paraphrase A",
        },
        {
            "role": "assistant", "content": "DANGEROUS_RAW_2",
            "tainted": True, "safe_summary": None,
        },
    ]
    out = _compose_with_history(history)

    # Continuity dialogue contains the safe paraphrase, not the raw
    assert "Safe paraphrase A" in out
    pre_wrapper, _, in_wrapper = out.partition("<untrusted_session_history>")
    assert "DANGEROUS_RAW_1" not in pre_wrapper
    # Raw-only row appears inside the wrapper
    assert "DANGEROUS_RAW_2" in in_wrapper


@pytest.mark.usefixtures("fresh_db")
def test_compose_clean_rows_unaffected() -> None:
    """Non-tainted rows still render as User/You dialogue, regardless
    of whether safe_summary is set or NULL."""
    history = [
        {"role": "user", "content": "Hello Donna", "tainted": False,
         "safe_summary": None},
        {"role": "assistant", "content": "Hi there!", "tainted": False,
         "safe_summary": None},
    ]
    out = _compose_with_history(history)
    assert "Hello Donna" in out
    assert "Hi there!" in out
    assert "<untrusted_session_history>" not in out


# ---------- handler tests moved to test_async_tasks.py -----------------
#
# v0.6 #2 (2026-05-02) replaced the fire-and-forget `_backfill_safe_summary`
# with a queue-backed `handle_safe_summary_backfill` runner handler. The
# three previously-here tests (success / sanitize-failure-graceful /
# empty-summary) are superseded by the new contract:
#
#   - test_handle_safe_summary_backfill_persists_on_success
#   - test_handle_safe_summary_backfill_raises_on_sanitize_error
#     (handler now PROPAGATES errors so the AsyncTaskRunner can apply
#      retry/dead-letter policy; v0.5.2 silenced them)
#   - test_handle_safe_summary_backfill_skips_empty_summary
#
# All in `tests/test_async_tasks.py`.


# ---------- migration shape ----------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_messages_safe_summary_column_exists() -> None:
    conn = connect()
    try:
        cols = {
            r["name"] for r in conn.execute(
                "PRAGMA table_info(messages)"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "safe_summary" in cols
