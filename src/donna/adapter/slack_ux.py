"""Slack UX — slash commands, modals, button handlers, message intake.

Mirror of v0.4.x's discord_ux.py, retooled for Slack primitives:

- Slash commands → app.command() handlers
- Button clicks (consent ✅/❌, modal triggers) → app.action() handlers
- Modal submissions (`/schedule` form) → app.view() handlers
- DM intake → app.event("message") with channel_type="im"
- Channel mentions → app.event("app_mention")

Block Kit replaces Discord embeds for richer rendering. Buttons replace
emoji reactions for consent (Codex review 2026-04-30): the action_id
+ button value carry the pending_id so the click handler can update
the right pending_consents row.

The /schedule UX is a modal rather than parsed slash args. Slack delivers
everything after the slash command as one raw `text` field, so structured
input via modal is the only sane way to collect cron + task + channel
+ mode without fragile regex parsing (Codex recommendation).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..config import settings
from ..logging import get_logger
from ..memory import cost as cost_mod
from ..memory import jobs as jobs_mod
from ..memory import prompts as prompts_mod
from ..memory import schedules as sched_mod
from ..memory import threads as threads_mod
from ..memory.db import connect, transaction
from ..security import consent as consent_mod
from ..types import JobMode, JobStatus

if TYPE_CHECKING:
    from .slack_adapter import DonnaSlackBot

log = get_logger(__name__)


# ============================================================================
# Block Kit templates
# ============================================================================


def consent_blocks(req: consent_mod.ConsentRequest) -> list[dict]:
    """Render a consent prompt as Block Kit. Buttons carry pending_id
    in their `value` so the action handler can match the row.

    Tainted requests get a 🔮 emoji + a reminder; clean requests get a
    ⚠️ . Either way, the operator clicks ✅ approve or ❌ decline.
    """
    icon = "🔮" if req.tainted else "⚠️"
    fields = [
        {"type": "mrkdwn", "text": f"*Tool:* `{req.tool_entry.name}`"},
        {"type": "mrkdwn", "text": f"*Scope:* `{req.tool_entry.scope}`"},
        {"type": "mrkdwn", "text": f"*Cost tier:* `{req.tool_entry.cost}`"},
        {"type": "mrkdwn", "text": f"*Tainted:* `{'yes' if req.tainted else 'no'}`"},
    ]
    args_summary = json.dumps(req.arguments, default=str)[:1500]
    body = (
        f"{icon} *Approve `{req.tool_entry.name}`?*\n"
        f"_Job_ `{req.job_id[:18]}…`"
    )
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": body},
            "fields": fields,
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"```{args_summary}```",
            },
        },
        {
            "type": "actions",
            "block_id": "consent_actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "consent_approve",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "value": req.pending_id,
                    "style": "primary",
                },
                {
                    "type": "button",
                    "action_id": "consent_decline",
                    "text": {"type": "plain_text", "text": "❌ Decline"},
                    "value": req.pending_id,
                    "style": "danger",
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "_Click a button above. Times out in 30 min._"},
            ],
        },
    ]


def job_blocks(job) -> list[dict]:
    """Render a /status job summary."""
    color_emoji = {
        "queued":   "⏳",
        "running":  "🔄",
        "paused_awaiting_consent": "⏸️",
        "done":     "✅",
        "failed":   "❌",
        "cancelled": "🚫",
    }.get(job.status.value, "•")
    fields = [
        {"type": "mrkdwn", "text": f"*Status:* `{job.status.value}`"},
        {"type": "mrkdwn", "text": f"*Mode:* `{job.mode.value}`"},
        {"type": "mrkdwn", "text": f"*Scope:* `{job.agent_scope}`"},
        {"type": "mrkdwn", "text": f"*Tool calls:* `{job.tool_call_count}`"},
        {"type": "mrkdwn", "text": f"*Cost:* `${job.cost_usd:.2f}`"},
        {"type": "mrkdwn", "text": f"*Tainted:* `{'yes' if job.tainted else 'no'}`"},
    ]
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{color_emoji} *Job* `{job.id[:18]}…`",
            },
            "fields": fields,
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"_Task:_\n{job.task[:500]}"},
        },
    ]
    if job.error:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"_Error:_\n```{job.error[:500]}```"},
        })
    return blocks


# ============================================================================
# Allowlist helpers (delegate to adapter for shared logic)
# ============================================================================


def _disable_schedule_by_id(conn, sid: str) -> str:
    """V60-5 (v0.6.2): shared helper for disabling a schedule by ID.

    Returns user-facing feedback for slash-command ack(). Handles the
    three cases:
    - schedule not found
    - already disabled
    - newly disabled (success)
    """
    row = conn.execute(
        "SELECT enabled FROM schedules WHERE id = ?", (sid,),
    ).fetchone()
    if row is None:
        return f"schedule `{sid[:20]}` not found"
    if not row["enabled"]:
        return f"schedule `{sid[:20]}` already disabled"
    with transaction(conn):
        sched_mod.disable_schedule(conn, sid)
    return f"🔕 disabled schedule `{sid[:20]}` (no further fires)"


def _cancel_job_by_id(conn, jid: str) -> str:
    """V60-5 (v0.6.2): shared helper for cancelling a job by ID.

    Existence check before set_status so a typo'd / non-existent ID
    doesn't silently succeed (pre-fix `jobs_mod.set_status` returned
    True regardless of rowcount when worker_id was None).
    """
    job = jobs_mod.get_job(conn, jid)
    if job is None:
        return (
            f"`{jid[:20]}` not found "
            "(no matching job; schedule IDs start with `sch_`)"
        )
    with transaction(conn):
        jobs_mod.set_status(conn, jid, JobStatus.CANCELLED)
    return f"cancelled job `{jid[:20]}`"


def _route_cancel_or_disable(target_id: str) -> str:
    """V60-5 (v0.6.2): smart-route a /donna_cancel target by ID prefix.

    - sch_... -> disable_schedule
    - other   -> cancel job

    Returns the user-facing feedback message.
    """
    conn = connect()
    try:
        if target_id.startswith("sch_"):
            return _disable_schedule_by_id(conn, target_id)
        return _cancel_job_by_id(conn, target_id)
    finally:
        conn.close()


def _is_allowed_command(body: dict) -> bool:
    """Verify the slash command came from the allowlisted user/team."""
    s = settings()
    team_id = body.get("team_id", "")
    user_id = body.get("user_id", "")
    return team_id == s.slack_team_id and user_id == s.slack_allowed_user_id


def _is_allowed_event(body: dict) -> bool:
    """Verify a message/app_mention event came from the allowlisted
    user/team. Returns False (silent reject) for off-allowlist; the
    bot ignores the event entirely."""
    from .slack_adapter import authorize_body
    return authorize_body(body)


# ============================================================================
# Registration
# ============================================================================


def register_handlers(bot: DonnaSlackBot) -> None:
    app = bot.app

    # --------------------------------------------------------------
    # Message intake: DM events
    # --------------------------------------------------------------

    @app.event("message")
    async def on_message(event, body, client):
        """Plain-text DM → create a chat-mode job."""
        # Filter subtypes (channel_join, message_changed, etc.)
        if event.get("subtype") is not None:
            return
        # Only react in DMs (channel_type="im"). For channel chatter use
        # @donna mention via the app_mention handler.
        if event.get("channel_type") != "im":
            return
        # Ignore the bot's own messages.
        if event.get("bot_id"):
            return
        if not _is_allowed_event(body):
            return

        content = (event.get("text") or "").strip()
        if not content:
            return

        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts")  # None if top-level DM

        # Bind a pending outbox_ask reply if there's one open in this
        # channel — same pattern as the Discord adapter. Slack
        # ts-strings replace Discord int IDs.
        conn = connect()
        try:
            row = conn.execute(
                "SELECT id FROM outbox_asks "
                "WHERE posted_channel_id = ? AND reply IS NULL "
                "ORDER BY created_at LIMIT 1",
                (channel_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks SET reply = ?, "
                        "replied_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND reply IS NULL",
                        (content, row["id"]),
                    )
            finally:
                conn.close()
            return

        # Otherwise, treat as a new chat-mode task.
        try:
            job_id = await _enqueue_dm_task(
                content=content,
                channel_id=channel_id,
                thread_ts=thread_ts,
                external_msg_id=event.get("ts"),
            )
        except CostCapExceeded as e:
            await _post_cost_cap_refusal(
                client, channel_id=channel_id,
                thread_ts=thread_ts, reason=e.reason,
            )
            return
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"📌 Job `{job_id[:18]}…` queued. I'll post updates here.",
            unfurl_links=False,
            unfurl_media=False,
        )

    @app.event("app_mention")
    async def on_app_mention(event, body, client):
        """@donna in a channel → create a chat-mode job and reply in
        thread. Channel chatter goes in-thread to keep #channel clean."""
        if not _is_allowed_event(body):
            return
        # Strip the bot mention prefix from the text.
        text_raw = event.get("text", "")
        # Slack mentions look like `<@U01...>`; strip everything before
        # the first space after the mention.
        content = (
            text_raw.split(">", 1)[1].strip()
            if ">" in text_raw else text_raw.strip()
        )
        if not content:
            return
        channel_id = event.get("channel")
        # In-thread reply: use the mention's own ts as thread_ts so the
        # reply lands in a thread instead of cluttering the channel.
        thread_ts = event.get("thread_ts") or event.get("ts")
        try:
            job_id = await _enqueue_dm_task(
                content=content,
                channel_id=channel_id,
                thread_ts=thread_ts,
                external_msg_id=event.get("ts"),
            )
        except CostCapExceeded as e:
            await _post_cost_cap_refusal(
                client, channel_id=channel_id,
                thread_ts=thread_ts, reason=e.reason,
            )
            return
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"📌 Job `{job_id[:18]}…` queued.",
            unfurl_links=False,
            unfurl_media=False,
        )

    # --------------------------------------------------------------
    # Consent buttons
    # --------------------------------------------------------------

    @app.action("consent_approve")
    async def on_consent_approve(ack, body, client):
        await ack()
        if not _is_allowed_command(_normalize_body_for_button(body)):
            return
        await _resolve_consent(body, client, approved=1)

    @app.action("consent_decline")
    async def on_consent_decline(ack, body, client):
        await ack()
        if not _is_allowed_command(_normalize_body_for_button(body)):
            return
        await _resolve_consent(body, client, approved=0)

    # --------------------------------------------------------------
    # Slash: /ask — scoped grounded query
    # --------------------------------------------------------------

    @app.command("/donna_ask")
    async def cmd_ask(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        # Slack delivers everything after /ask as one raw text. Parse:
        # `<scope>: <question...>` — scope before the first colon, the
        # rest is the question. Fallback: scope=orchestrator if no colon.
        raw = (body.get("text") or "").strip()
        scope, question = _parse_scope_question(raw)
        if not question:
            await ack(
                text="Usage: `/ask <scope>: <question>` — e.g. "
                     "`/ask author_twain: walk through Huck's moral arc`"
            )
            return
        try:
            jid = await _enqueue_slash_task(
                body=body,
                content=question,
                agent_scope=scope,
                mode=JobMode.GROUNDED,
            )
        except CostCapExceeded as e:
            await ack(text=f":warning: cost cap engaged ({e.reason}) — try again later")
            return
        await ack(
            text=f"📌 Job `{jid[:18]}…` queued · scope `{scope}` · "
                 f"mode `grounded`",
        )

    @app.command("/donna_speculate")
    async def cmd_speculate(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        raw = (body.get("text") or "").strip()
        scope, question = _parse_scope_question(raw)
        if not question:
            await ack(text="Usage: `/speculate <scope>: <question>`")
            return
        try:
            jid = await _enqueue_slash_task(
                body=body, content=question, agent_scope=scope,
                mode=JobMode.SPECULATIVE,
            )
        except CostCapExceeded as e:
            await ack(text=f":warning: cost cap engaged ({e.reason}) — try again later")
            return
        await ack(text=f"📌 Job `{jid[:18]}…` queued · mode `speculative`")

    @app.command("/donna_debate")
    async def cmd_debate(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        raw = (body.get("text") or "").strip()
        # `/debate scope_a vs scope_b on topic [rounds]`
        # Minimal parsing: look for "vs" and "on" markers.
        try:
            scope_a, rest = raw.split(" vs ", 1)
            scope_b, topic_etc = rest.split(" on ", 1)
            topic_parts = topic_etc.rsplit(" ", 1)
            if topic_parts[-1].isdigit():
                topic = " ".join(topic_parts[:-1])
                rounds = int(topic_parts[-1])
            else:
                topic = topic_etc
                rounds = 3
        except ValueError:
            await ack(
                text="Usage: `/debate <scope_a> vs <scope_b> on <topic> [rounds]`"
            )
            return
        task = json.dumps({
            "scope_a": scope_a.strip(),
            "scope_b": scope_b.strip(),
            "topic": topic.strip(),
            "rounds": rounds,
        })
        try:
            jid = await _enqueue_slash_task(
                body=body, content=task, agent_scope="orchestrator",
                mode=JobMode.DEBATE,
            )
        except CostCapExceeded as e:
            await ack(text=f":warning: cost cap engaged ({e.reason}) — try again later")
            return
        await ack(text=f"📌 Debate job `{jid[:18]}…` queued · {rounds} rounds")

    # --------------------------------------------------------------
    # Slash: /schedule (opens modal)
    # --------------------------------------------------------------

    @app.command("/donna_schedule")
    async def cmd_schedule(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        await ack()
        # Open a modal with cron, task, channel-target, mode fields.
        # Slack slash-arg parsing is bad, so we collect structured
        # input via modal (Codex review).
        try:
            await client.views_open(
                trigger_id=body["trigger_id"],
                view=_schedule_modal_view(initial_channel=body.get("channel_id")),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("slack.schedule_modal_open_failed", error=str(e))

    @app.view("schedule_modal")
    async def on_schedule_submit(ack, body, view, client):
        if not _is_allowed_command(_normalize_body_for_view(body)):
            await ack(response_action="errors",
                      errors={"cron_block": "not authorized"})
            return
        state = view.get("state", {}).get("values", {})
        cron_expr = (
            state.get("cron_block", {})
                 .get("cron_input", {})
                 .get("value", "")
                 .strip()
        )
        task = (
            state.get("task_block", {})
                 .get("task_input", {})
                 .get("value", "")
                 .strip()
        )
        # Channel select returns selected_conversation; might be None
        channel_state = (
            state.get("channel_block", {})
                 .get("channel_input", {})
        )
        target_channel_id = channel_state.get("selected_conversation")

        # Mode radio
        mode_state = (
            state.get("mode_block", {})
                 .get("mode_input", {})
        )
        mode = (
            mode_state.get("selected_option", {}).get("value", "chat")
        )

        # Validate cron at the data layer; surface friendly error in modal
        try:
            conn = connect()
            try:
                # Capture the originating thread for fallback delivery
                # if no target channel was picked.
                with transaction(conn):
                    # Use a placeholder thread; if no target_channel_id
                    # provided, fall back to the originating slash
                    # command's channel (stashed in private_metadata
                    # when the modal was opened) so the schedule still
                    # delivers somewhere.
                    tid = None
                    if not target_channel_id:
                        target_channel_id = view.get("private_metadata") or None
                    if target_channel_id:
                        tid = threads_mod.get_or_create_thread(
                            conn,
                            channel_id=target_channel_id,
                            thread_external_id=None,
                        )
                    sid = sched_mod.insert_schedule(
                        conn,
                        cron_expr=cron_expr,
                        task=task,
                        mode=mode,
                        thread_id=tid,
                        target_channel_id=target_channel_id,
                    )
                row = conn.execute(
                    "SELECT next_run_at FROM schedules WHERE id = ?",
                    (sid,),
                ).fetchone()
            finally:
                conn.close()
        except ValueError as e:
            stripped = cron_expr.strip()
            hint = ""
            if stripped and " " not in stripped:
                hint = (
                    " (cron needs 5 space-separated fields — e.g. "
                    "`* * * * *` for every minute)"
                )
            await ack(
                response_action="errors",
                errors={
                    "cron_block": f"invalid cron `{cron_expr}` — {e}{hint}",
                },
            )
            return

        await ack()  # close modal
        next_run = row["next_run_at"] if row else "?"
        # Confirm in DM (where the user invoked /schedule).
        try:
            user_id = body.get("user", {}).get("id")
            await client.chat_postMessage(
                channel=user_id,  # DM the user
                text=(
                    f"📅 scheduled `{sid}` — `{cron_expr}` ({mode})\n"
                    f"   next fire: *{next_run} UTC*\n"
                    f"   task: {task[:500]}\n"
                    + (f"   destination: <#{target_channel_id}>"
                       if target_channel_id else
                       "   destination: (default — your DM)")
                ),
                unfurl_links=False,
                unfurl_media=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("slack.schedule_confirm_failed", error=str(e))

    # --------------------------------------------------------------
    # Slash: /schedules (list)
    # --------------------------------------------------------------

    @app.command("/donna_schedules")
    async def cmd_schedules(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        conn = connect()
        try:
            items = sched_mod.list_schedules(conn)
        finally:
            conn.close()
        if not items:
            await ack(
                text="no active schedules — add one with `/schedule`",
            )
            return
        lines = [f"*{len(items)} active schedule(s)*"]
        for s in items:
            last = s.get("last_run_at") or "never"
            target = (
                f"<#{s['target_channel_id']}>"
                if s.get("target_channel_id") else
                "(DM default)"
            )
            lines.append(
                f"• `{s['id']}` `{s['cron_expr']}` → {target}\n"
                f"   next: {s['next_run_at']} UTC · last fired: {last}\n"
                f"   {s['task'][:200]}"
            )
        await ack(text="\n".join(lines))

    # --------------------------------------------------------------
    # Slash: /donna_validate <url> [claim]
    # --------------------------------------------------------------

    @app.command("/donna_validate")
    async def cmd_validate(ack, body, client):
        # v0.7.1: URL-bounded grounded critique. Operator pastes a URL
        # (and optional claim to evaluate); Donna fetches with SSRF
        # protection, chunks ephemerally, and runs grounded validation.
        # Slash handler must ack within Slack's 3s timeout — the actual
        # work runs in the worker.
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        raw = (body.get("text") or "").strip()
        if not raw:
            await ack(
                text=(
                    "Usage: `/donna_validate <url> [optional claim]` "
                    "— I'll fetch the URL safely (no localhost / "
                    "private IPs / cloud metadata), chunk it, and "
                    "produce a critique with verbatim citations."
                )
            )
            return

        # Pre-flight URL safety so the operator gets fast feedback on a
        # malformed/unsafe URL instead of waiting for the worker.
        from ..security.url_safety import UnsafeURL, assert_safe_url
        url, _, claim = raw.partition(" ")
        url = url.strip()
        claim = claim.strip() or None
        try:
            assert_safe_url(url)
        except UnsafeURL as e:
            await ack(text=f"unsafe URL: {e.reason}")
            return

        channel_id = body.get("channel_id")
        try:
            conn = connect()
            try:
                with transaction(conn):
                    tid = threads_mod.get_or_create_thread(
                        conn, channel_id=channel_id,
                        thread_external_id=None,
                    )
                    # Compose task in the format run_validate expects.
                    task = (
                        url if claim is None
                        else f"{url}\n---\nclaim: {claim}"
                    )
                    jid = jobs_mod.insert_job(
                        conn, task=task, mode=JobMode.VALIDATE,
                        thread_id=tid,
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning("slack.validate_enqueue_failed", error=str(e))
            await ack(text=f"failed to queue validation: {e}")
            return

        await ack(
            text=(
                f"📑 validating `{url[:60]}` — job `{jid[:18]}…`. "
                "I'll post the critique here when complete."
            )
        )

    # --------------------------------------------------------------
    # Slash: /donna_brief_setup (modal) + /donna_brief_run_now
    # --------------------------------------------------------------

    @app.command("/donna_brief_setup")
    async def cmd_brief_setup(ack, body, client):
        # v0.7.0: configure a daily morning brief. Modal collects
        # cron + channel + topics list. Slash command must ack
        # immediately and open the modal — no inline LLM work
        # (Codex blind-spot rule for Slack handlers).
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        await ack()
        try:
            await client.views_open(
                trigger_id=body["trigger_id"],
                view=_brief_setup_modal_view(
                    initial_channel=body.get("channel_id"),
                ),
            )
        except Exception as e:  # noqa: BLE001
            log.warning("slack.brief_setup_modal_open_failed", error=str(e))

    @app.view("brief_setup_modal")
    async def on_brief_setup_submit(ack, body, view, client):
        if not _is_allowed_command(_normalize_body_for_view(body)):
            await ack(response_action="errors",
                      errors={"cron_block": "not authorized"})
            return
        state = view.get("state", {}).get("values", {})
        cron_expr = (
            state.get("cron_block", {})
                 .get("cron_input", {})
                 .get("value", "")
                 .strip()
        )
        topics_raw = (
            state.get("topics_block", {})
                 .get("topics_input", {})
                 .get("value", "")
                 .strip()
        )
        # Topics: one per line OR comma-separated. Both are common
        # operator habits.
        topics: list[str] = []
        for chunk in topics_raw.replace(",", "\n").split("\n"):
            t = chunk.strip(" -*•·").strip()
            if t:
                topics.append(t)

        channel_state = (
            state.get("channel_block", {})
                 .get("channel_input", {})
        )
        target_channel_id = channel_state.get("selected_conversation")
        if not target_channel_id:
            target_channel_id = view.get("private_metadata") or None

        tz = (
            state.get("tz_block", {})
                 .get("tz_input", {})
                 .get("value", "")
                 .strip()
            or None
        )
        style = (
            state.get("style_block", {})
                 .get("style_input", {})
                 .get("value", "")
                 .strip()
            or None
        )

        if not target_channel_id:
            await ack(
                response_action="errors",
                errors={
                    "channel_block": (
                        "morning brief needs a target channel — pick "
                        "where it should be delivered."
                    ),
                },
            )
            return

        try:
            conn = connect()
            try:
                with transaction(conn):
                    tid = threads_mod.get_or_create_thread(
                        conn,
                        channel_id=target_channel_id,
                        thread_external_id=None,
                    )
                    payload = {
                        "topics": topics,
                        "tz": tz,
                        "style": style,
                    }
                    sid = sched_mod.insert_schedule(
                        conn,
                        cron_expr=cron_expr,
                        task=(
                            "Morning brief: see schedule.payload_json "
                            "for topics + style."
                        ),
                        mode="chat",
                        thread_id=tid,
                        target_channel_id=target_channel_id,
                        kind="morning_brief",
                        payload=payload,
                    )
                    row = conn.execute(
                        "SELECT next_run_at FROM schedules WHERE id = ?",
                        (sid,),
                    ).fetchone()
            finally:
                conn.close()
        except ValueError as e:
            stripped = cron_expr.strip()
            hint = ""
            if stripped and " " not in stripped:
                hint = (
                    " (cron needs 5 space-separated fields — e.g. "
                    "`0 12 * * *` for daily 12:00 UTC)"
                )
            await ack(
                response_action="errors",
                errors={
                    "cron_block": f"invalid cron `{cron_expr}` — {e}{hint}",
                },
            )
            return

        await ack()
        next_run = row["next_run_at"] if row else "?"
        try:
            user_id = body.get("user", {}).get("id")
            await client.chat_postMessage(
                channel=user_id,
                text=(
                    f"📰 morning brief scheduled `{sid}` — "
                    f"`{cron_expr}` UTC\n"
                    f"   next fire: *{next_run} UTC*\n"
                    f"   destination: <#{target_channel_id}>\n"
                    f"   topics: "
                    + (", ".join(topics) if topics else "(none — "
                       "Donna will pick from your saved knowledge)")
                    + "\n   dry-run any time with: "
                      f"`/donna_brief_run_now {sid}`"
                ),
                unfurl_links=False,
                unfurl_media=False,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("slack.brief_setup_confirm_failed", error=str(e))

    @app.command("/donna_brief_run_now")
    async def cmd_brief_run_now(ack, body, client):
        # v0.7.0: dry run a configured brief on demand. Useful for
        # operator-driven validation right after /donna_brief_setup
        # without waiting for the cron tick.
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        sid = (body.get("text") or "").strip()
        if not sid:
            await ack(
                text=(
                    "Usage: `/donna_brief_run_now <sch_...>` — "
                    "list with `/donna_schedules`."
                )
            )
            return
        if not sid.startswith("sch_"):
            await ack(
                text=(
                    f"`{sid[:20]}` is not a schedule id "
                    "(must start with `sch_`)"
                )
            )
            return
        from ..jobs.morning_brief import fire_morning_brief_now

        jid = fire_morning_brief_now(schedule_id=sid)
        if jid is None:
            await ack(
                text=(
                    f"`{sid[:20]}`: not found, not a morning_brief "
                    "kind, or no destination configured. Check "
                    "`/donna_schedules`."
                )
            )
            return
        await ack(
            text=(
                f"📰 brief running on demand — job `{jid[:18]}…`. "
                "Will post to the configured channel when complete."
            )
        )

    # --------------------------------------------------------------
    # Slash: /history /budget /cancel /status
    # --------------------------------------------------------------

    @app.command("/donna_history")
    async def cmd_history(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        try:
            limit = int((body.get("text") or "10").strip())
        except ValueError:
            limit = 10
        conn = connect()
        try:
            jobs = jobs_mod.recent_jobs(conn, limit=limit)
        finally:
            conn.close()
        if not jobs:
            await ack(text="no jobs yet")
            return
        lines = [
            f"• `{j.id[:18]}` [{j.status.value}] {j.task[:80]}"
            for j in jobs
        ]
        await ack(text="\n".join(lines))

    @app.command("/donna_budget")
    async def cmd_budget(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        conn = connect()
        try:
            spent = cost_mod.spend_today(conn)
        finally:
            conn.close()
        thresholds = settings().budget_thresholds
        await ack(
            text=f"💰 Spent today: *${spent:.2f}* · alerts at: "
                 + ", ".join(f"${t:.0f}" for t in thresholds),
        )

    @app.command("/donna_cancel")
    async def cmd_cancel(ack, body, client):
        # V60-5 (v0.6.2): smart-route by ID prefix.
        #
        # Pre-fix this command silently no-op'd when given a schedule
        # ID (sch_...) because jobs_mod.set_status executes
        # `UPDATE jobs WHERE id = ?` and returns True regardless of
        # rowcount. Operator hit this 2026-05-02 trying to stop a
        # `* * * * *` test schedule — `/donna_cancel sch_...` returned
        # "cancelled" twice but the schedule kept firing every minute.
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        target_id = (body.get("text") or "").strip()
        if not target_id:
            await ack(
                text=(
                    "Usage: `/donna_cancel <id>` — accepts a job id "
                    "(`job_...`) or schedule id (`sch_...`)."
                )
            )
            return
        await ack(text=_route_cancel_or_disable(target_id))

    @app.command("/donna_schedule_disable")
    async def cmd_schedule_disable(ack, body, client):
        # V60-5 (v0.6.2): explicit semantics for stopping a runaway
        # schedule from Slack. /donna_cancel smart-routes to the same
        # path, but this exists so the operator never has to wonder
        # whether `/donna_cancel sch_...` cancels a single fire or the
        # whole schedule.
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        sid = (body.get("text") or "").strip()
        if not sid:
            await ack(
                text=(
                    "Usage: `/donna_schedule_disable <sch_...>` — "
                    "list with `/donna_schedules`."
                )
            )
            return
        if not sid.startswith("sch_"):
            await ack(
                text=(
                    f"`{sid[:20]}` is not a schedule id "
                    "(must start with `sch_`)"
                )
            )
            return
        conn = connect()
        try:
            msg = _disable_schedule_by_id(conn, sid)
        finally:
            conn.close()
        await ack(text=msg)

    @app.command("/donna_status")
    async def cmd_status(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        job_id = (body.get("text") or "").strip()
        if not job_id:
            await ack(text="Usage: `/status <job-id>`")
            return
        conn = connect()
        try:
            job = jobs_mod.get_job(conn, job_id)
        finally:
            conn.close()
        if not job:
            await ack(text=f"no such job: {job_id}")
            return
        await ack(blocks=job_blocks(job), text=f"Job {job.id[:18]}…")

    # --------------------------------------------------------------
    # Slash: /model /heuristics /approve_heuristic
    # --------------------------------------------------------------

    @app.command("/donna_model")
    async def cmd_model(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        tier_arg = (body.get("text") or "").strip().lower()
        valid = {"fast", "strong", "heavy", "clear"}
        if tier_arg not in valid:
            await ack(
                text=f"Usage: `/model fast|strong|heavy|clear` "
                     f"(got `{tier_arg or '(empty)'}`)",
            )
            return
        channel_id = body.get("channel_id", "")
        conn = connect()
        try:
            with transaction(conn):
                thread_id = threads_mod.find_by_channel(
                    conn, channel_id=channel_id,
                )
                if thread_id is None:
                    thread_id = threads_mod.get_or_create_thread(
                        conn,
                        channel_id=channel_id,
                        thread_external_id=None,
                    )
                new_tier = None if tier_arg == "clear" else tier_arg
                threads_mod.set_model_tier_override(
                    conn, thread_id=thread_id, tier=new_tier,
                )
        finally:
            conn.close()
        msg = (
            "🔄 Model override cleared — using default (strong/Sonnet)."
            if tier_arg == "clear" else
            f"🎚 Model tier for this channel → *{tier_arg}*. "
            f"Jobs queued after this will use it."
        )
        await ack(text=msg)

    @app.command("/donna_heuristics")
    async def cmd_heuristics(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        scope = (body.get("text") or "").strip() or "orchestrator"
        conn = connect()
        try:
            hs = prompts_mod.active_heuristics(conn, scope)
        finally:
            conn.close()
        if not hs:
            await ack(text=f"(no active heuristics for `{scope}`)")
            return
        await ack(text="\n".join(f"• {h}" for h in hs))

    @app.command("/donna_approve_heuristic")
    async def cmd_approve_h(ack, body, client):
        if not _is_allowed_command(body):
            await ack(text="not authorized")
            return
        hid = (body.get("text") or "").strip()
        if not hid:
            await ack(text="Usage: `/approve_heuristic <heuristic-id>`")
            return
        conn = connect()
        try:
            with transaction(conn):
                prompts_mod.approve_heuristic(conn, heuristic_id=hid)
        finally:
            conn.close()
        await ack(text=f"✅ approved {hid}")


# ============================================================================
# Helpers
# ============================================================================


def _parse_scope_question(raw: str) -> tuple[str, str]:
    """Parse `<scope>: <question>` from a slash-command text payload.

    `/ask author_twain: walk through Huck's moral arc`
        → ("author_twain", "walk through Huck's moral arc")

    Falls back to scope=`orchestrator` if no colon is present.
    """
    if ":" in raw:
        scope_part, question = raw.split(":", 1)
        scope = scope_part.strip() or "orchestrator"
        return scope, question.strip()
    return "orchestrator", raw.strip()


def _normalize_body_for_button(body: dict) -> dict:
    """Block actions deliver team/user nested. Reshape to look like a
    slash command body so `_is_allowed_command` can be reused."""
    return {
        "team_id": body.get("team", {}).get("id", ""),
        "user_id": body.get("user", {}).get("id", ""),
    }


def _normalize_body_for_view(body: dict) -> dict:
    """View submissions also deliver team/user nested."""
    return _normalize_body_for_button(body)


class CostCapExceeded(Exception):
    """v0.6 #7: raised by intake helpers when the daily/weekly hard cap
    is exceeded. Caller catches it and posts a refusal reply instead of
    creating a job."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _enqueue_dm_task(
    *,
    content: str,
    channel_id: str,
    thread_ts: str | None,
    external_msg_id: str | None,
) -> str:
    """Insert a job for a DM/app-mention and return the job_id.

    Does NOT write the user message to `messages` at intake — that's
    `JobContext.finalize`'s responsibility (v0.4.3 dedup fix).

    v0.6 #7: raises CostCapExceeded if the daily/weekly hard cap is hit.
    """
    from ..observability import cost_guard
    status = cost_guard.current_status()
    if status.blocked:
        raise CostCapExceeded(status.reason())
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn,
                channel_id=channel_id,
                thread_external_id=thread_ts,
                title=content[:60],
            )
            jid = jobs_mod.insert_job(
                conn, task=content, thread_id=tid,
            )
    finally:
        conn.close()
    return jid


async def _enqueue_slash_task(
    *, body: dict, content: str, agent_scope: str, mode: JobMode,
) -> str:
    """Insert a job for a slash command. Captures the originating
    channel as the destination thread.

    v0.6 #7: raises CostCapExceeded if the daily/weekly hard cap is hit.
    """
    from ..observability import cost_guard
    status = cost_guard.current_status()
    if status.blocked:
        raise CostCapExceeded(status.reason())
    channel_id = body.get("channel_id") or ""
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn,
                channel_id=channel_id,
                thread_external_id=None,
            )
            jid = jobs_mod.insert_job(
                conn,
                task=content,
                agent_scope=agent_scope,
                mode=mode,
                thread_id=tid,
            )
    finally:
        conn.close()
    return jid


async def _post_cost_cap_refusal(
    client, *, channel_id: str, thread_ts: str | None, reason: str,
) -> None:
    """Polite refusal posted when intake hits the hard cap. Same message
    shape across all intake paths (DM, app_mention, slash command)."""
    text = (
        ":warning: Donna's cost cap is engaged — refusing new work.\n"
        f"_{reason}_\n"
        "Operator: clear with `botctl cost` and raise "
        "`DONNA_DAILY_HARD_CAP_USD` / `DONNA_WEEKLY_HARD_CAP_USD` if "
        "needed, or wait until the rolling window slides."
    )
    try:
        await client.chat_postMessage(
            channel=channel_id, thread_ts=thread_ts, text=text,
            unfurl_links=False, unfurl_media=False,
        )
    except Exception as e:  # noqa: BLE001
        from ..logging import get_logger
        get_logger(__name__).warning(
            "slack.cost_cap_refusal_failed", error=str(e),
        )


async def _resolve_consent(body: dict, client, *, approved: int) -> None:
    """Update pending_consents based on a button click. Edits the
    posted message via chat.update to remove the buttons (so the
    operator can't double-click) and shows the resolution outcome."""
    actions = body.get("actions") or []
    if not actions:
        return
    pending_id = actions[0].get("value")
    if not pending_id:
        return
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE pending_consents "
                "SET approved = ?, decided_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND approved IS NULL",
                (approved, pending_id),
            )
        # Look up posted_message_id + channel for chat.update
        row = conn.execute(
            "SELECT posted_channel_id, posted_message_id, tool_name "
            "FROM pending_consents WHERE id = ?",
            (pending_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return
    icon = "✅" if approved else "❌"
    label = "Approved" if approved else "Declined"
    try:
        await client.chat_update(
            channel=row["posted_channel_id"],
            ts=row["posted_message_id"],
            text=f"{icon} {label}: `{row['tool_name']}`",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{icon} *{label}:* `{row['tool_name']}`",
                    },
                }
            ],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("slack.consent_chat_update_failed",
                    error=str(e), pending_id=pending_id)


def _schedule_modal_view(*, initial_channel: str | None = None) -> dict:
    """Return the Block Kit view payload for the /schedule modal."""
    channel_input = {
        "type": "conversations_select",
        "action_id": "channel_input",
        "placeholder": {
            "type": "plain_text",
            "text": "Pick a channel for the reply (optional)",
        },
        "filter": {"include": ["public", "private", "im"]},
    }
    if initial_channel:
        channel_input["initial_conversation"] = initial_channel

    return {
        "type": "modal",
        "callback_id": "schedule_modal",
        "title": {"type": "plain_text", "text": "Add a schedule"},
        "submit": {"type": "plain_text", "text": "Schedule"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": initial_channel or "",
        "blocks": [
            {
                "type": "input",
                "block_id": "cron_block",
                "label": {"type": "plain_text", "text": "Cron expression (UTC)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "cron_input",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "* * * * *  (every minute) — 5 fields, space-separated",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "task_block",
                "label": {"type": "plain_text", "text": "Task (what should Donna do?)"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "task_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "e.g. What's new in AI today? 4 bullet points.",
                    },
                },
            },
            {
                "type": "input",
                "block_id": "channel_block",
                "label": {"type": "plain_text", "text": "Where should the reply go?"},
                "element": channel_input,
                "optional": True,
            },
            {
                "type": "input",
                "block_id": "mode_block",
                "label": {"type": "plain_text", "text": "Mode"},
                "element": {
                    "type": "radio_buttons",
                    "action_id": "mode_input",
                    "initial_option": {
                        "value": "chat",
                        "text": {"type": "plain_text", "text": "chat"},
                    },
                    "options": [
                        {"value": "chat",
                         "text": {"type": "plain_text", "text": "chat"}},
                        {"value": "grounded",
                         "text": {"type": "plain_text", "text": "grounded"}},
                        {"value": "speculative",
                         "text": {"type": "plain_text", "text": "speculative"}},
                    ],
                },
            },
        ],
    }


def _brief_setup_modal_view(*, initial_channel: str | None = None) -> dict:
    """v0.7.0: morning brief setup modal.

    Collects cron + target channel + topics list (free-form, comma- or
    newline-separated) + optional tz label and style hint. Persists as
    a schedule with kind='morning_brief' and payload_json carrying the
    topic list.
    """
    channel_input: dict = {
        "type": "conversations_select",
        "action_id": "channel_input",
        "placeholder": {
            "type": "plain_text",
            "text": "Pick a channel for daily brief delivery",
        },
        "filter": {"include": ["public", "private", "im"]},
    }
    if initial_channel:
        channel_input["initial_conversation"] = initial_channel

    return {
        "type": "modal",
        "callback_id": "brief_setup_modal",
        "title": {"type": "plain_text", "text": "Morning brief setup"},
        "submit": {"type": "plain_text", "text": "Schedule brief"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": initial_channel or "",
        "blocks": [
            {
                "type": "input",
                "block_id": "cron_block",
                "label": {
                    "type": "plain_text",
                    "text": "Cron expression (UTC)",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "cron_input",
                    "placeholder": {
                        "type": "plain_text",
                        "text": (
                            "0 12 * * *  (daily 12:00 UTC = 8am EDT / "
                            "7am EST)"
                        ),
                    },
                },
            },
            {
                "type": "input",
                "block_id": "channel_block",
                "label": {
                    "type": "plain_text",
                    "text": "Where should the brief go?",
                },
                "element": channel_input,
            },
            {
                "type": "input",
                "block_id": "topics_block",
                "label": {
                    "type": "plain_text",
                    "text": "Topics (comma- or line-separated)",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "topics_input",
                    "multiline": True,
                    "placeholder": {
                        "type": "plain_text",
                        "text": (
                            "AI safety, rate limiting, personal-AI "
                            "products, climate policy"
                        ),
                    },
                },
                "optional": True,
            },
            {
                "type": "input",
                "block_id": "tz_block",
                "label": {
                    "type": "plain_text",
                    "text": "Your timezone label (display only, e.g. America/New_York)",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "tz_input",
                },
                "optional": True,
            },
            {
                "type": "input",
                "block_id": "style_block",
                "label": {
                    "type": "plain_text",
                    "text": "Style hint (optional, e.g. 'punchy bullets, no fluff')",
                },
                "element": {
                    "type": "plain_text_input",
                    "action_id": "style_input",
                },
                "optional": True,
            },
        ],
    }
