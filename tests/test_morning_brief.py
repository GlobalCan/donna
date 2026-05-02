"""V0.7.0: morning brief vertical slice — idempotency, payload, dispatch.

Codex 2026-05-02 review on the overnight plan flagged the must-haves:

- Idempotency via brief_runs(schedule_id, fire_key) UNIQUE key.
  Duplicate scheduler ticks must produce exactly one delivered brief.
- AsyncTaskRunner is the wrong runner for actual brief work (60s
  lease, no heartbeat). Brief composition runs in the normal jobs /
  JobContext path.
- Topic count caps so a misconfigured payload can't fan out to 50
  search calls.
- Slash command writes config + returns fast (no inline LLM).
- Brief output is tainted (web/news tools).

These tests lock those properties in.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest

from donna.jobs import morning_brief as brief_mod
from donna.jobs.scheduler import Scheduler
from donna.memory import brief_runs as br_mod
from donna.memory import schedules as sched_mod
from donna.memory import threads as threads_mod
from donna.memory.db import connect, transaction

# ---------- helpers --------------------------------------------------------


def _make_morning_brief_schedule(
    *,
    target_channel_id: str = "C_BRIEF",
    cron: str = "0 12 * * *",
    topics: list[str] | None = None,
    tz: str | None = "America/New_York",
) -> str:
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn,
                channel_id=target_channel_id,
                thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr=cron,
                task="brief auto-generated",
                mode="chat",
                thread_id=tid,
                target_channel_id=target_channel_id,
                kind="morning_brief",
                payload={
                    "topics": topics if topics is not None else
                              ["AI safety", "rate limiting"],
                    "tz": tz,
                },
            )
    finally:
        conn.close()
    return sid


def _load_schedule(sid: str) -> dict:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (sid,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row)


# ---------- fire_key bucketing ---------------------------------------------


def test_fire_key_truncates_to_minute() -> None:
    """Two calls within the same minute compute the same fire_key —
    the basis for the UNIQUE-constraint dedup."""
    a = datetime(2026, 5, 2, 12, 0, 5, tzinfo=UTC)
    b = datetime(2026, 5, 2, 12, 0, 45, tzinfo=UTC)
    assert br_mod.fire_key_for(a) == br_mod.fire_key_for(b)


def test_fire_key_different_minutes_differ() -> None:
    a = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)
    b = datetime(2026, 5, 2, 12, 1, 0, tzinfo=UTC)
    assert br_mod.fire_key_for(a) != br_mod.fire_key_for(b)


def test_fire_key_naive_datetime_treated_as_utc() -> None:
    """Defensive: a caller passing a naive datetime should not crash
    — we coerce to UTC."""
    naive = datetime(2026, 5, 2, 12, 0, 0)
    aware = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)
    assert br_mod.fire_key_for(naive) == br_mod.fire_key_for(aware)


# ---------- payload parsing ------------------------------------------------


def test_compose_seed_includes_topics() -> None:
    payload = {"topics": ["foo", "bar"], "tz": "America/New_York"}
    seed = brief_mod.compose_brief_seed_prompt(payload=payload)
    assert "foo" in seed
    assert "bar" in seed
    assert "America/New_York" in seed


def test_compose_seed_handles_no_topics_gracefully() -> None:
    """Empty topics shouldn't produce a malformed prompt — fall back
    to 'pick from saved knowledge' guidance."""
    payload = {"topics": [], "tz": None}
    seed = brief_mod.compose_brief_seed_prompt(payload=payload)
    assert "saved knowledge corpus" in seed.lower()


def test_payload_caps_topic_count() -> None:
    """v0.7.0: hard cap at MAX_TOPICS so a misconfigured payload
    can't spawn a 50-topic brief that hammers the search budget."""
    payload_json = json.dumps({"topics": [f"t{i}" for i in range(50)]})
    parsed = brief_mod._parse_payload(payload_json)
    assert len(parsed["topics"]) == brief_mod.MAX_TOPICS


def test_payload_truncates_long_topics() -> None:
    long_topic = "x" * 500
    payload_json = json.dumps({"topics": [long_topic]})
    parsed = brief_mod._parse_payload(payload_json)
    assert len(parsed["topics"][0]) == brief_mod.TOPIC_CHAR_LIMIT


def test_payload_invalid_json_returns_empty_topics() -> None:
    """Defensive: a corrupted payload_json shouldn't crash the
    scheduler — return empty topics + log warning."""
    parsed = brief_mod._parse_payload("not-json{")
    assert parsed["topics"] == []


# ---------- fire_morning_brief ---------------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_fire_creates_chat_job_and_brief_run() -> None:
    """Single fire writes one job (chat mode, schedule_id back-link)
    and one brief_run row."""
    sid = _make_morning_brief_schedule(topics=["alpha", "beta"])
    sched = _load_schedule(sid)
    fire_at = datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC)

    jid = brief_mod.fire_morning_brief(sched=sched, fire_at=fire_at)
    assert jid is not None

    conn = connect()
    try:
        job_row = conn.execute(
            "SELECT mode, schedule_id, task FROM jobs WHERE id = ?",
            (jid,),
        ).fetchone()
        runs = conn.execute(
            "SELECT schedule_id, fire_key, job_id, status "
            "FROM brief_runs WHERE schedule_id = ?",
            (sid,),
        ).fetchall()
    finally:
        conn.close()

    assert job_row["mode"] == "chat"
    assert job_row["schedule_id"] == sid
    assert "alpha" in job_row["task"]
    assert len(runs) == 1
    assert runs[0]["job_id"] == jid


@pytest.mark.usefixtures("fresh_db")
def test_fire_dedupes_within_minute() -> None:
    """Codex's blocking requirement: two fires for the same minute
    must produce exactly one delivered brief. Even if the second call
    runs 45s later, fire_key is bucketed to the minute so the second
    INSERT is a no-op."""
    sid = _make_morning_brief_schedule()
    sched = _load_schedule(sid)
    fire_at_a = datetime(2026, 5, 2, 12, 0, 5, tzinfo=UTC)
    fire_at_b = datetime(2026, 5, 2, 12, 0, 45, tzinfo=UTC)

    jid_a = brief_mod.fire_morning_brief(sched=sched, fire_at=fire_at_a)
    jid_b = brief_mod.fire_morning_brief(sched=sched, fire_at=fire_at_b)

    assert jid_a is not None
    assert jid_b is None  # loser of the race

    conn = connect()
    try:
        runs = conn.execute(
            "SELECT id FROM brief_runs WHERE schedule_id = ?", (sid,),
        ).fetchall()
        # Loser's job row must NOT have leaked.
        jobs = conn.execute(
            "SELECT id FROM jobs WHERE schedule_id = ?", (sid,),
        ).fetchall()
    finally:
        conn.close()

    assert len(runs) == 1
    assert len(jobs) == 1
    assert jobs[0]["id"] == jid_a


@pytest.mark.usefixtures("fresh_db")
def test_fire_with_no_destination_logs_and_returns_none() -> None:
    """Schedule without target_channel_id AND without thread_id has
    nowhere to deliver. Better to return None + log loud than create
    orphan jobs."""
    conn = connect()
    try:
        with transaction(conn):
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="0 12 * * *",
                task="brief",
                mode="chat",
                kind="morning_brief",
                payload={"topics": ["x"]},
                # No thread_id, no target_channel_id
            )
    finally:
        conn.close()
    sched = _load_schedule(sid)

    jid = brief_mod.fire_morning_brief(
        sched=sched, fire_at=datetime.now(UTC),
    )
    assert jid is None


@pytest.mark.usefixtures("fresh_db")
def test_fire_morning_brief_now_dispatches_to_correct_schedule() -> None:
    """/donna_brief_run_now must reach the right schedule by ID."""
    sid = _make_morning_brief_schedule(topics=["dry-run"])
    jid = brief_mod.fire_morning_brief_now(schedule_id=sid)
    assert jid is not None

    conn = connect()
    try:
        row = conn.execute(
            "SELECT schedule_id, task FROM jobs WHERE id = ?", (jid,),
        ).fetchone()
    finally:
        conn.close()
    assert row["schedule_id"] == sid
    assert "dry-run" in row["task"]


@pytest.mark.usefixtures("fresh_db")
def test_fire_morning_brief_now_rejects_wrong_kind() -> None:
    """A non-brief schedule must not be hijacked by run-now."""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_X", thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="0 12 * * *",
                task="legacy task",
                thread_id=tid,
                target_channel_id="C_X",
                # kind defaults to 'task'
            )
    finally:
        conn.close()

    jid = brief_mod.fire_morning_brief_now(schedule_id=sid)
    assert jid is None


@pytest.mark.usefixtures("fresh_db")
def test_fire_morning_brief_now_rejects_unknown_schedule() -> None:
    jid = brief_mod.fire_morning_brief_now(schedule_id="sch_unknown_xxx")
    assert jid is None


# ---------- Scheduler dispatch by kind --------------------------------------


@pytest.mark.usefixtures("fresh_db")
def test_scheduler_dispatches_morning_brief_kind() -> None:
    """v0.7.0: when Scheduler._fire sees kind='morning_brief', it goes
    through brief_mod.fire_morning_brief, not the legacy task path.
    Result: a brief_run row exists alongside the job."""
    sid = _make_morning_brief_schedule()
    sched = _load_schedule(sid)

    asyncio.run(Scheduler()._fire(sched))

    conn = connect()
    try:
        runs = conn.execute(
            "SELECT id FROM brief_runs WHERE schedule_id = ?", (sid,),
        ).fetchall()
        jobs = conn.execute(
            "SELECT id, mode, schedule_id FROM jobs "
            "WHERE schedule_id = ?", (sid,),
        ).fetchall()
    finally:
        conn.close()

    assert len(runs) == 1
    assert len(jobs) == 1
    assert jobs[0]["mode"] == "chat"


@pytest.mark.usefixtures("fresh_db")
def test_scheduler_legacy_task_kind_still_works() -> None:
    """Existing schedules with kind='task' (default for pre-v0.7 rows)
    continue to fire the legacy free-form task path. No brief_run is
    created for them."""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn, channel_id="C_LEGACY",
                thread_external_id=None,
            )
            sid = sched_mod.insert_schedule(
                conn,
                cron_expr="0 12 * * *",
                task="legacy task",
                mode="chat",
                thread_id=tid,
                target_channel_id="C_LEGACY",
                # kind defaults to 'task'
            )
    finally:
        conn.close()
    sched = _load_schedule(sid)

    asyncio.run(Scheduler()._fire(sched))

    conn = connect()
    try:
        runs = conn.execute(
            "SELECT id FROM brief_runs WHERE schedule_id = ?", (sid,),
        ).fetchall()
        jobs = conn.execute(
            "SELECT id FROM jobs WHERE schedule_id = ?", (sid,),
        ).fetchall()
    finally:
        conn.close()

    assert len(runs) == 0  # no brief_run for kind='task'
    assert len(jobs) == 1


# ---------- claim_brief_run idempotency at the SQL layer --------------------


@pytest.mark.usefixtures("fresh_db")
def test_botctl_brief_runs_list_renders_recent_runs() -> None:
    """Smoke test the operator panel: after a fire, `botctl brief-runs
    list` should render the row."""
    from typer.testing import CliRunner

    from donna.cli.botctl import app as cli_app
    sid = _make_morning_brief_schedule()
    sched = _load_schedule(sid)
    brief_mod.fire_morning_brief(
        sched=sched,
        fire_at=datetime(2026, 5, 2, 12, 0, 0, tzinfo=UTC),
    )

    runner = CliRunner()
    result = runner.invoke(cli_app, ["brief-runs", "list"])
    assert result.exit_code == 0, result.output
    # Rich's table truncates long cells to fit terminal width — assert
    # on a prefix short enough to survive truncation.
    assert sid[:8] in result.output


@pytest.mark.usefixtures("fresh_db")
def test_botctl_brief_runs_list_empty_state() -> None:
    """When there are no runs, the command should say so cleanly
    rather than rendering an empty table."""
    from typer.testing import CliRunner

    from donna.cli.botctl import app as cli_app
    runner = CliRunner()
    result = runner.invoke(cli_app, ["brief-runs", "list"])
    assert result.exit_code == 0, result.output
    assert "no brief runs yet" in result.output


@pytest.mark.usefixtures("fresh_db")
def test_claim_brief_run_returns_true_on_first_insert_and_false_on_dup() -> None:
    """Locking down the helper directly so the dedup contract is
    bullet-proof regardless of caller behavior."""
    sid = _make_morning_brief_schedule()
    # need a real job for the FK
    conn = connect()
    try:
        with transaction(conn):
            from donna.memory import jobs as jobs_mod
            from donna.types import JobMode
            jid = jobs_mod.insert_job(
                conn, task="brief", mode=JobMode.CHAT,
            )
        with transaction(conn):
            won_a = br_mod.claim_brief_run(
                conn, schedule_id=sid,
                fire_key="2026-05-02T12:00:00+00:00", job_id=jid,
            )
        with transaction(conn):
            won_b = br_mod.claim_brief_run(
                conn, schedule_id=sid,
                fire_key="2026-05-02T12:00:00+00:00", job_id=jid,
            )
    finally:
        conn.close()
    assert won_a is True
    assert won_b is False
