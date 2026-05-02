"""Morning brief — v0.7.0 first proactive product workflow.

Codex 2026-05-02 review framed the design constraints:

- Use `schedules` (kind='morning_brief') as the cron + destination
  source of truth. Don't duplicate cron logic in a parallel
  brief_configs table.
- Idempotency belongs in `brief_runs(schedule_id, fire_key)` with a
  unique key. Duplicate scheduler ticks (within-minute races, retries,
  multi-worker setups) must produce exactly one delivered brief.
- Brief composition is real long-running agent work (news + search +
  model + synthesis). Run it in the normal `jobs` table / JobContext
  path with full heartbeat + retry semantics. AsyncTaskRunner has a
  60s lease and no heartbeat — wrong tool for this job.
- Slash command writes config + returns fast. No inline generation.
- Brief output is tainted because tools touch web/news. JobContext
  finalize handles taint propagation; outbox / drainer renders with
  the tainted-content wrapper.

This module hosts the seed-prompt composer + `fire_morning_brief`
which Scheduler._fire calls when it sees a kind='morning_brief'
schedule.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from ..logging import get_logger
from ..memory import brief_runs as br_mod
from ..memory import jobs as jobs_mod
from ..memory.db import connect, transaction
from ..types import JobMode

log = get_logger(__name__)

# Hard caps so a misconfigured payload can't spawn a 50-topic brief
# that hammers the search budget. v0.6 #7 cost guards already cap
# total spend; these are pre-spend sanity bounds.
MAX_TOPICS = 8
TOPIC_CHAR_LIMIT = 80


def _parse_payload(payload_json: str | None) -> dict:
    if not payload_json:
        return {"topics": [], "tz": None}
    try:
        d = json.loads(payload_json)
    except (ValueError, TypeError):
        log.warning("morning_brief.payload_invalid_json", payload=payload_json[:200])
        return {"topics": [], "tz": None}
    topics = d.get("topics") or []
    if not isinstance(topics, list):
        topics = []
    topics = [str(t).strip()[:TOPIC_CHAR_LIMIT] for t in topics if str(t).strip()]
    topics = topics[:MAX_TOPICS]
    return {
        "topics": topics,
        "tz": d.get("tz"),
        "style": d.get("style"),  # optional voice/length preference
    }


def compose_brief_seed_prompt(
    *,
    payload: dict,
    fire_at_local: str | None = None,
) -> str:
    """Produce the seed task string a scheduled brief job runs as.

    The agent loop will then pick tools (search_news, recall_knowledge,
    fetch_url) and synthesize a prose summary. Output is delivered via
    the normal JobContext.finalize -> outbox path.
    """
    topics = payload.get("topics") or []
    tz_label = payload.get("tz") or "UTC"
    style = (payload.get("style") or "").strip()

    if topics:
        topic_lines = "\n".join(f"- {t}" for t in topics)
        topic_block = f"Topics to cover:\n{topic_lines}"
    else:
        topic_block = (
            "No specific topics were configured. Surface the most "
            "notable recent items the operator would want to know "
            "about based on the saved knowledge corpus."
        )

    when = fire_at_local or datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    style_hint = f"Tone/style preference: {style}\n\n" if style else ""

    return (
        f"# Morning brief — {when} ({tz_label})\n\n"
        f"{topic_block}\n\n"
        f"{style_hint}"
        "For each topic, do a quick news/search lookup and pull "
        "anything notable from saved facts/artifacts. Synthesize "
        "into a concise brief: per-topic bullet of the headline + "
        "one or two sentences of context. Cite sources where possible. "
        "Skip topics with nothing notable rather than padding. End "
        "with a one-line tl;dr."
    )


def fire_morning_brief(
    *, sched: dict, fire_at: datetime,
) -> str | None:
    """Fire a morning_brief schedule. Returns the new job_id, or None
    if the fire_key was already claimed (duplicate scheduler tick) or
    there is no destination to deliver to.

    Caller (Scheduler._fire) is responsible for marking the schedule's
    next_run_at AFTER this returns, regardless of whether we won the
    race — that bookkeeping shouldn't block on the brief itself.
    """
    payload = _parse_payload(sched.get("payload_json"))
    fire_key = br_mod.fire_key_for(fire_at)

    if not sched.get("target_channel_id") and not sched.get("thread_id"):
        # No destination — the brief would generate output that the
        # drainer can't deliver. Better to log loud than silently
        # accumulate orphan jobs.
        log.error(
            "morning_brief.no_destination",
            schedule_id=sched["id"],
            fire_key=fire_key,
        )
        return None

    seed = compose_brief_seed_prompt(payload=payload)

    conn = connect()
    try:
        with transaction(conn):
            jid = jobs_mod.insert_job(
                conn,
                task=seed,
                agent_scope=sched.get("agent_scope", "orchestrator"),
                mode=JobMode.CHAT,
                thread_id=sched.get("thread_id"),
                schedule_id=sched["id"],
            )
            won = br_mod.claim_brief_run(
                conn,
                schedule_id=sched["id"],
                fire_key=fire_key,
                job_id=jid,
            )
            if not won:
                # Loser of the race: roll back the just-created job
                # so we don't leak an orphan brief job.
                conn.execute("DELETE FROM jobs WHERE id = ?", (jid,))
                log.info(
                    "morning_brief.duplicate_fire_skipped",
                    schedule_id=sched["id"],
                    fire_key=fire_key,
                )
                return None
    finally:
        conn.close()

    log.info(
        "morning_brief.fired",
        schedule_id=sched["id"],
        job_id=jid,
        fire_key=fire_key,
        target_channel_id=sched.get("target_channel_id"),
        topic_count=len(payload.get("topics") or []),
    )
    return jid


def fire_morning_brief_now(*, schedule_id: str) -> str | None:
    """Operator-triggered dry run for /donna_brief_run_now.

    Same fire path as the scheduled fire but with fire_at=now (so it
    has its own fire_key bucketed to the current minute and won't
    conflict with the regular schedule unless they happen to overlap
    within the same minute).
    """
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM schedules WHERE id = ?", (schedule_id,),
        ).fetchone()
        sched = dict(row) if row else None
    finally:
        conn.close()
    if sched is None:
        log.error("morning_brief.run_now_unknown_schedule",
                  schedule_id=schedule_id)
        return None
    if sched.get("kind") != "morning_brief":
        log.error("morning_brief.run_now_wrong_kind",
                  schedule_id=schedule_id, kind=sched.get("kind"))
        return None
    return fire_morning_brief(sched=sched, fire_at=datetime.now(UTC))
