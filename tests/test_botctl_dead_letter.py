"""V0.6 #3: `botctl dead-letter` + `botctl async-tasks` operator UX tests.

Covers list / show / retry / discard for outbox_dead_letter (the v0.5.1
table that captures terminal/unknown delivery failures), plus the
read-only list/show for v0.6 async_tasks.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from donna.cli.botctl import app
from donna.memory import async_tasks as at_mod
from donna.memory import dead_letter as dl_mod
from donna.memory import jobs as jobs_mod
from donna.memory.db import connect, transaction

runner = CliRunner()


def _make_job() -> str:
    conn = connect()
    try:
        with transaction(conn):
            return jobs_mod.insert_job(conn, task="t")
    finally:
        conn.close()


def _make_dl(
    *, source_id: str = "out_abc", channel: str = "C_DEAD",
    error_code: str = "not_in_channel", error_class: str = "terminal",
    payload: str = "undeliverable text", attempts: int = 3,
) -> str:
    job_id = _make_job()
    conn = connect()
    try:
        with transaction(conn):
            return dl_mod.record_dead_letter(
                conn,
                source_table="outbox_updates",
                source_id=source_id,
                job_id=job_id,
                channel_id=channel,
                thread_ts=None,
                payload=payload,
                tainted=False,
                error_code=error_code,
                error_class=error_class,
                attempt_count=attempts,
                first_attempt_at=None,
            )
    finally:
        conn.close()


# ---------- dead-letter list ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_list_shows_rows() -> None:
    dl_id = _make_dl(error_code="not_in_channel")
    result = runner.invoke(app, ["dead-letter", "list"])
    assert result.exit_code == 0, result.output
    # Rich's table truncates long cells to fit terminal width — assert
    # on prefixes that survive truncation.
    assert dl_id[:9] in result.output  # dl id prefix is enough
    assert "not_in_cha" in result.output
    assert "C_DEAD" in result.output
    assert "terminal" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_list_empty_state() -> None:
    result = runner.invoke(app, ["dead-letter", "list"])
    assert result.exit_code == 0
    assert "no dead-letter rows match" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_list_filters_by_class() -> None:
    """`--class unknown` hides terminal rows and vice versa."""
    _make_dl(error_code="not_in_channel", error_class="terminal")
    unknown_id = _make_dl(
        source_id="out_xyz", error_code="brand_new_err",
        error_class="unknown",
    )
    result = runner.invoke(
        app, ["dead-letter", "list", "--class", "unknown"],
    )
    assert result.exit_code == 0
    assert unknown_id[:9] in result.output
    assert "brand_new" in result.output
    # The terminal-class row should be excluded — check both full and
    # truncated forms.
    assert "not_in_channel" not in result.output
    assert "not_in_cha" not in result.output


# ---------- dead-letter show ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_show_prints_full_row() -> None:
    dl_id = _make_dl(payload="full payload that should print")
    result = runner.invoke(app, ["dead-letter", "show", dl_id])
    assert result.exit_code == 0, result.output
    assert dl_id in result.output
    assert "outbox_updates" in result.output  # source_table
    assert "C_DEAD" in result.output           # channel_id
    assert "not_in_channel" in result.output   # error_code
    assert "full payload that should print" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_show_truncates_huge_payload() -> None:
    """A payload over 2000 chars renders only the first 2000 to avoid
    flooding the terminal."""
    big = "x" * 5000
    dl_id = _make_dl(payload=big)
    result = runner.invoke(app, ["dead-letter", "show", dl_id])
    assert result.exit_code == 0
    assert "5000 chars" in result.output
    # Truncated marker present, not all 5000 chars rendered
    assert result.output.count("x") < 5000


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_show_unknown_id_exits_nonzero() -> None:
    result = runner.invoke(app, ["dead-letter", "show", "dl_does_not_exist"])
    assert result.exit_code == 1
    assert "not found" in result.output


# ---------- dead-letter retry --------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_retry_reenqueues_to_outbox_and_deletes_row() -> None:
    dl_id = _make_dl(payload="please deliver me")
    result = runner.invoke(
        app, ["dead-letter", "retry", dl_id, "--force"],
    )
    assert result.exit_code == 0, result.output
    assert "re-enqueued" in result.output

    # Source row gone, outbox_updates has a fresh row with the payload
    conn = connect()
    try:
        dl_row = conn.execute(
            "SELECT id FROM outbox_dead_letter WHERE id = ?", (dl_id,),
        ).fetchone()
        outbox_row = conn.execute(
            "SELECT text FROM outbox_updates "
            "WHERE text = 'please deliver me' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert dl_row is None
    assert outbox_row is not None
    assert outbox_row["text"] == "please deliver me"


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_retry_unknown_id_exits_nonzero() -> None:
    result = runner.invoke(
        app, ["dead-letter", "retry", "dl_nope", "--force"],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_retry_rejects_unsupported_source_table() -> None:
    """If a future kind dead-letters from a non-outbox_updates source,
    the retry path must refuse rather than guess."""
    job_id = _make_job()
    conn = connect()
    try:
        with transaction(conn):
            dl_id = dl_mod.record_dead_letter(
                conn, source_table="future_table", source_id="x",
                job_id=job_id, channel_id="C_X", thread_ts=None,
                payload="p", tainted=False, error_code="x",
                error_class="terminal", attempt_count=1,
                first_attempt_at=None,
            )
    finally:
        conn.close()
    result = runner.invoke(
        app, ["dead-letter", "retry", dl_id, "--force"],
    )
    assert result.exit_code == 2
    assert "not supported" in result.output


# ---------- dead-letter discard ------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_discard_deletes_row() -> None:
    dl_id = _make_dl()
    result = runner.invoke(
        app, ["dead-letter", "discard", dl_id, "--force"],
    )
    assert result.exit_code == 0
    assert "discarded" in result.output
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM outbox_dead_letter WHERE id = ?", (dl_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is None


@pytest.mark.usefixtures("fresh_db")
def test_dead_letter_discard_unknown_id_exits_nonzero() -> None:
    result = runner.invoke(
        app, ["dead-letter", "discard", "dl_nope", "--force"],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


# ---------- async-tasks list / show --------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_async_tasks_list_shows_rows_and_totals() -> None:
    conn = connect()
    try:
        with transaction(conn):
            at_mod.enqueue(
                conn, kind="safe_summary_backfill",
                payload={"message_id": "msg_x"},
            )
    finally:
        conn.close()
    result = runner.invoke(app, ["async-tasks", "list"])
    assert result.exit_code == 0, result.output
    # Title carries the totals line WITHOUT truncation. Cell rendering
    # truncates the kind name, so check the totals + a prefix.
    assert "pending=1" in result.output
    assert "safe_summa" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_async_tasks_list_filters_by_status_and_kind() -> None:
    conn = connect()
    try:
        with transaction(conn):
            at_mod.enqueue(conn, kind="kind_a", payload={"x": 1})
            at_mod.enqueue(conn, kind="kind_b", payload={"x": 2})
    finally:
        conn.close()
    result = runner.invoke(
        app, ["async-tasks", "list", "--kind", "kind_a"],
    )
    assert result.exit_code == 0
    assert "kind_a" in result.output
    # totals header would summarize pending=2 if we hadn't filtered;
    # post-filter the table only shows kind_a, so kind_b shouldn't appear.
    # Note: count_by_status reflects ALL rows (not the filter), so
    # "pending=2" still appears in the totals header — that's fine.
    # What matters: only one kind_a row in the table body.
    assert "kind_b" not in result.output


@pytest.mark.usefixtures("fresh_db")
def test_async_tasks_list_empty_state() -> None:
    result = runner.invoke(app, ["async-tasks", "list"])
    assert result.exit_code == 0
    assert "empty" in result.output or "no rows match" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_async_tasks_show_prints_full_row() -> None:
    conn = connect()
    try:
        with transaction(conn):
            tid = at_mod.enqueue(
                conn, kind="safe_summary_backfill",
                payload={"message_id": "msg_x", "content": "hi"},
            )
    finally:
        conn.close()
    result = runner.invoke(app, ["async-tasks", "show", tid])
    assert result.exit_code == 0, result.output
    assert tid in result.output
    assert "safe_summary_backfill" in result.output
    assert "pending" in result.output
    # Payload rendered
    payload_line_present = any(
        "msg_x" in line for line in result.output.splitlines()
    )
    assert payload_line_present


@pytest.mark.usefixtures("fresh_db")
def test_async_tasks_show_unknown_id_exits_nonzero() -> None:
    result = runner.invoke(app, ["async-tasks", "show", "at_nope"])
    assert result.exit_code == 1
    assert "not found" in result.output


# Sanity check that the JSON payload survives the round trip through enqueue
@pytest.mark.usefixtures("fresh_db")
def test_async_tasks_show_payload_round_trips_json() -> None:
    payload = {"message_id": "msg_y", "content": "raw", "job_id": "j1"}
    conn = connect()
    try:
        with transaction(conn):
            tid = at_mod.enqueue(
                conn, kind="safe_summary_backfill", payload=payload,
            )
    finally:
        conn.close()
    result = runner.invoke(app, ["async-tasks", "show", tid])
    assert result.exit_code == 0
    assert "msg_y" in result.output
    # Round-trip through JSON
    conn = connect()
    try:
        row = conn.execute(
            "SELECT payload FROM async_tasks WHERE id = ?", (tid,),
        ).fetchone()
    finally:
        conn.close()
    assert json.loads(row["payload"]) == payload
