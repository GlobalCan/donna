"""Slack adapter — message intake, outbox drain, slash commands,
button-based consent. v0.5.0 replacement for the v0.4.x Discord adapter.

Architecture mirror of the Discord adapter:

- Intake: DM events (message.im) + app mentions → insert a Job, reply
  with the job id
- Outbox: poll outbox_updates / outbox_asks / pending_consents tables;
  post into Slack via Web API
- Buttons: ✅ approve / ❌ decline buttons on consent cards drive
  pending_consents.approved (Slack equivalent of Discord reactions —
  Codex review 2026-04-30 recommended Block Kit buttons over reactions)
- Slash commands: /ask /schedule (modal) /schedules /history /budget
  /cancel /status /model /heuristics /approve_heuristic and friends

Why Socket Mode:
  Donna runs on a single droplet with no inbound HTTPS endpoint. Socket
  Mode pushes events to the bot's outbound WebSocket — same connection
  shape as Discord's gateway. No request URL to manage; no
  signing-secret verification needed; works behind any firewall that
  permits outbound HTTPS.

Rate limits:
  Slack expects roughly 1 message/sec per channel (Codex review). The
  drainer maintains a per-channel last-sent-at map; a job whose channel
  is already at limit waits one poll cycle. This is in addition to
  the per-job 5s rate limit on progress updates we inherited from the
  Discord adapter.

Untrusted-content safety:
  Tainted messages get `&`, `<`, `>` HTML-style escaped before posting;
  unfurls are disabled (`unfurl_links=False`, `unfurl_media=False`)
  so accidental URL mentions in untrusted content don't expand into
  rich previews. Codex review recommendation; without these escapes a
  fetched page could trigger @-mention notifications or link-preview
  side effects.

Allowlist:
  Every event verifies team_id matches SLACK_TEAM_ID and user_id matches
  SLACK_ALLOWED_USER_ID. Defense in depth — if a bot token leaked across
  workspaces, requests from a different team would be silently rejected.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from ..config import settings
from ..logging import get_logger
from ..memory import dead_letter as dl_mod
from ..memory import jobs as jobs_mod
from ..memory.db import connect, transaction
from ..security import consent as consent_mod
from ..tools import registry as tool_registry
from . import slack_ux
from .slack_errors import (
    ErrorClass,
    classify_error_code,
    extract_error_code,
    extract_retry_after_seconds,
)

log = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class PostResult:
    """Outcome of a single chat.postMessage attempt.

    On success: ok=True, all other fields None.
    On SlackApiError: ok=False with error_code + error_class set.
    On other exceptions (network, timeout): ok=False, error_code=None,
    error_class=UNKNOWN. retry_after_s is set only when Slack returned
    rate_limited with a Retry-After header.
    """
    ok: bool
    error_code: str | None = None
    error_class: ErrorClass | None = None
    retry_after_s: float | None = None
    error_msg: str | None = None


# DB poll cadence for outbox drains. 1s feels instant in Slack just
# like in Discord.
_DRAIN_POLL_S = 1.0
# Per-job rate limit for progress updates. Inherits the Discord cadence.
_UPDATE_RATE_LIMIT_S = 5.0
# Per-channel rate limit. Slack guidance is ~1 msg/sec/channel; we use
# a slightly more conservative 1.2s. Codex review 2026-04-30.
_CHANNEL_RATE_LIMIT_S = 1.2

# Slack section block text limit — 3000 chars per block. chat.postMessage
# top-level text recommends 4000 chars. We use 3500 as the inline cap so
# answers can split into Block Kit sections cleanly without flirting
# with either limit. Anything over the overflow caps gets compartment-
# alized to an artifact (preserving the v0.4.x security pattern).
_SLACK_SECTION_LIMIT = 3500
_OVERFLOW_CLEAN_MAX = _SLACK_SECTION_LIMIT * 4   # ~14k chars across 4 blocks
_OVERFLOW_TAINTED_MAX = _SLACK_SECTION_LIMIT * 1
_OVERFLOW_PREVIEW_LEN = 1500


# ============================================================================
# Allowlist
# ============================================================================


def _extract_team_user(body: dict) -> tuple[str, str | None]:
    """Slack payload shapes differ by event type. Block actions and view
    submissions nest team/user; slash commands and message events flatten
    them. Pulled from the Phase-0 smoke harness so both code paths share
    the same extraction logic.
    """
    team_id = body.get("team_id") or body.get("team", {}).get("id", "")
    user_id = body.get("user_id")
    if not user_id:
        user_obj = body.get("user")
        if isinstance(user_obj, dict):
            user_id = user_obj.get("id")
    if not user_id:
        # Message events: body["event"]["user"]
        event = body.get("event")
        if isinstance(event, dict):
            user_id = event.get("user")
    return team_id, user_id


def is_authorized(team_id: str, user_id: str | None) -> bool:
    s = settings()
    if team_id != s.slack_team_id:
        return False
    return user_id == s.slack_allowed_user_id


def authorize_body(body: dict) -> bool:
    team_id, user_id = _extract_team_user(body)
    return is_authorized(team_id, user_id)


# ============================================================================
# Block Kit rendering helpers
# ============================================================================


def _escape_for_slack(text: str) -> str:
    """Escape characters Slack interprets for mentions, channels, and
    links: `&`, `<`, `>`. Codex review 2026-04-30: untrusted content
    that contains `<@U123456>` would otherwise materialize as a real
    @-mention in Slack and notify whoever U123456 is. Same risk for
    channel refs `<#C12345>` and link rewrites `<https://evil>`.

    Idempotent. Run on tainted text only — clean assistant prose may
    legitimately contain markdown that we want to preserve.
    """
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )


def _split_for_slack(text: str, limit: int = _SLACK_SECTION_LIMIT) -> list[str]:
    """Split `text` into Slack-safe chunks, preferring paragraph
    boundaries, then sentence terminators, then a hard cut.

    Returns `[text]` if already ≤ limit. Mirror of the Discord adapter's
    splitter, retuned for Slack's 3000-char section block limit (we use
    3500 so the splitter has slack to find a clean boundary).
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    min_chunk = limit // 3
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", min_chunk, limit)
        if cut < 0:
            for term in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
                idx = remaining.rfind(term, min_chunk, limit)
                if idx > cut:
                    cut = idx + len(term) - 1
        if cut < 0:
            cut = remaining.rfind("\n", min_chunk, limit)
        if cut < 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


# ============================================================================
# Bot lifecycle
# ============================================================================


class DonnaSlackBot:
    def __init__(self) -> None:
        s = settings()
        self.app = AsyncApp(token=s.slack_bot_token)
        self.client: AsyncWebClient = self.app.client
        self.handler = AsyncSocketModeHandler(self.app, s.slack_app_token)
        self._drain_tasks: list[asyncio.Task] = []
        self._last_sent_per_channel: dict[str, float] = {}
        # V50-1: hard per-channel cool-down when Slack returns rate_limited
        # with a Retry-After header. Honored before the soft per-channel
        # pacing gate; values are absolute time.time() epochs.
        self._rate_limited_until: dict[str, float] = {}
        slack_ux.register_handlers(self)

    async def start(self) -> None:
        log.info("slack.start")
        # Spawn drainers BEFORE handler.start_async() blocks so they
        # come up alongside the WebSocket. _supervise wraps each in
        # exponential-backoff restart on transient failure.
        self._drain_tasks = [
            asyncio.create_task(self._supervise("drain_updates", self._drain_updates)),
            asyncio.create_task(self._supervise("drain_consent", self._drain_consent)),
            asyncio.create_task(self._supervise("drain_asks", self._drain_asks)),
        ]
        await self.handler.start_async()

    async def _supervise(self, name: str, coro_factory) -> None:
        """Run a drainer coroutine forever; on exception log + restart
        with capped exponential backoff. Mirror of the Discord adapter
        pattern."""
        backoff = 1.0
        while True:
            try:
                await coro_factory()
                log.warning("slack.drainer.exited_normally", name=name)
                backoff = 1.0
            except asyncio.CancelledError:
                log.info("slack.drainer.cancelled", name=name)
                raise
            except Exception as e:  # noqa: BLE001
                log.error(
                    "slack.drainer.crashed",
                    name=name, error=str(e), backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    # ------------------------------------------------------------------
    # Outbox: progress updates
    # ------------------------------------------------------------------

    async def _drain_updates(self) -> None:
        """Poll outbox_updates, post oldest-first per (job, channel), branch
        on the post outcome (V50-1):

          - ok       -> DELETE row (current path)
          - transient-> bump attempt_count + last_error + last_attempt_at,
                        leave row in place; if Retry-After present, set a
                        per-channel hard cool-down so we don't hammer
          - terminal -> log WARN, INSERT outbox_dead_letter, DELETE source row
          - unknown  -> same as terminal (operator inspects dead-letter to
                        decide if the code should join TRANSIENT_ERRORS)

        Two rate-limit gates exist:
          1. Hard per-channel cool-down `self._rate_limited_until` honored
             after a real `rate_limited` response with Retry-After.
          2. Soft per-channel pacing `self._last_sent_per_channel` (~1.2s),
             always applied to keep us under Slack's per-channel guideline.
        """
        last_sent_per_job: dict[str, float] = {}
        while True:
            await asyncio.sleep(_DRAIN_POLL_S)
            conn = connect()
            try:
                rows = conn.execute(
                    "SELECT id, job_id, text, tainted, "
                    "attempt_count, created_at "
                    "FROM outbox_updates "
                    "ORDER BY created_at LIMIT 50"
                ).fetchall()
            finally:
                conn.close()

            for row in rows:
                job_id = row["job_id"]
                now = time.time()
                if (now - last_sent_per_job.get(job_id, 0.0)) < _UPDATE_RATE_LIMIT_S:
                    continue
                ch = await self._resolve_channel_for_job(job_id, row["text"])
                if ch is None:
                    # Can't resolve — leave the row; could be a transient
                    # job-not-yet-claimed condition.
                    continue
                # Hard rate-limit cool-down (Slack Retry-After). Overrides
                # soft pacing.
                if now < self._rate_limited_until.get(ch, 0.0):
                    continue
                # Soft pacing.
                if (now - self._last_sent_per_channel.get(ch, 0.0)) < _CHANNEL_RATE_LIMIT_S:
                    continue
                thread_ts = await self._resolve_thread_ts_for_job(job_id)
                result = await self._post_update(
                    channel=ch,
                    job_id=job_id,
                    thread_ts=thread_ts,
                    text=row["text"],
                    tainted=bool(row["tainted"]),
                )
                self._handle_update_result(
                    row=row, channel=ch, thread_ts=thread_ts,
                    result=result, last_sent_per_job=last_sent_per_job,
                )

    def _handle_update_result(
        self,
        *,
        row,
        channel: str,
        thread_ts: str | None,
        result: PostResult,
        last_sent_per_job: dict[str, float],
    ) -> None:
        """Apply the V50-1 routing rules to a single drain attempt.

        Mutates `last_sent_per_job` and `self._last_sent_per_channel` /
        `self._rate_limited_until` in place. Performs DB writes per the
        result.error_class branch.
        """
        row_id = row["id"]
        job_id = row["job_id"]
        attempt_count = (row["attempt_count"] or 0) + 1
        now_epoch = time.time()

        if result.ok:
            last_sent_per_job[job_id] = now_epoch
            self._last_sent_per_channel[channel] = now_epoch
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "DELETE FROM outbox_updates WHERE id = ?", (row_id,),
                    )
            finally:
                conn.close()
            return

        cls = result.error_class or ErrorClass.UNKNOWN
        error_code = result.error_code or "unknown"
        # Structured observability: error_code + retry class + attempt
        # count + channel + row age make stuck rows obvious.
        row_age_s: float | None = None
        try:
            created_at = row["created_at"]
            if created_at is not None:
                ca = (
                    datetime.fromisoformat(created_at)
                    if isinstance(created_at, str)
                    else created_at
                )
                if ca.tzinfo is None:
                    ca = ca.replace(tzinfo=UTC)
                row_age_s = (datetime.now(UTC) - ca).total_seconds()
        except (TypeError, ValueError):
            row_age_s = None

        if cls is ErrorClass.TRANSIENT:
            # Keep the row alive; update visibility columns. If Slack gave a
            # hard Retry-After, set the per-channel cool-down too.
            log.info(
                "slack.update_transient",
                error_code=error_code,
                error_class=cls.value,
                attempt_count=attempt_count,
                channel=channel,
                job_id=job_id,
                row_age_s=row_age_s,
                retry_after_s=result.retry_after_s,
            )
            if result.retry_after_s is not None and result.retry_after_s > 0:
                # Cap to 5 minutes — anything bigger means the bot is
                # severely throttled; better to recover via the supervisor
                # restart than wait silently.
                wait_s = min(result.retry_after_s, 300.0)
                self._rate_limited_until[channel] = now_epoch + wait_s
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_updates "
                        "SET attempt_count = ?, last_error = ?, "
                        "last_attempt_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (attempt_count, error_code, row_id),
                    )
            finally:
                conn.close()
            return

        # TERMINAL or UNKNOWN: dead-letter + delete the source row.
        log.warning(
            "slack.update_dead_letter",
            error_code=error_code,
            error_class=cls.value,
            attempt_count=attempt_count,
            channel=channel,
            job_id=job_id,
            row_age_s=row_age_s,
            error_msg=result.error_msg,
        )
        # Resolve the schedule-or-thread first attempt time; we use
        # outbox_updates.created_at as a good-enough proxy.
        first_attempt_at: datetime | None = None
        try:
            ca = row["created_at"]
            if ca is not None:
                first_attempt_at = (
                    datetime.fromisoformat(ca)
                    if isinstance(ca, str)
                    else ca
                )
                if first_attempt_at.tzinfo is None:
                    first_attempt_at = first_attempt_at.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            first_attempt_at = None
        conn = connect()
        try:
            with transaction(conn):
                dl_mod.record_dead_letter(
                    conn,
                    source_table="outbox_updates",
                    source_id=row_id,
                    job_id=job_id,
                    channel_id=channel,
                    thread_ts=thread_ts,
                    payload=row["text"],
                    tainted=bool(row["tainted"]),
                    error_code=error_code,
                    error_class=cls.value,
                    attempt_count=attempt_count,
                    first_attempt_at=first_attempt_at,
                )
                conn.execute(
                    "DELETE FROM outbox_updates WHERE id = ?", (row_id,),
                )
        finally:
            conn.close()

    async def _post_update(
        self,
        *,
        channel: str,
        job_id: str,
        thread_ts: str | None,
        text: str,
        tainted: bool,
    ) -> PostResult:
        """Post a progress update or final answer. Long content goes via
        overflow-to-artifact (preserving v0.4.x security pattern); short
        content goes inline as Block Kit sections.

        Returns PostResult with classification details on failure so the
        drainer can route transient/terminal/unknown distinctly (V50-1).
        """
        cap = _OVERFLOW_TAINTED_MAX if tainted else _OVERFLOW_CLEAN_MAX
        if len(text) > cap:
            return await self._post_overflow_pointer(
                channel=channel, thread_ts=thread_ts,
                job_id=job_id, text=text, tainted=tainted,
            )

        prefix = "🔮 " if tainted else "• "
        # For tainted text, escape Slack's mention/link metacharacters so
        # untrusted bytes can't materialize @-mentions or link-preview
        # rewrites. Clean text passes through unmangled.
        rendered = _escape_for_slack(text) if tainted else text
        parts = _split_for_slack(rendered)
        try:
            for i, part in enumerate(parts, start=1):
                header = prefix if len(parts) == 1 else f"{prefix}({i}/{len(parts)}) "
                await self.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"{header}{part}",
                    unfurl_links=not tainted,
                    unfurl_media=not tainted,
                )
                if len(parts) > 1 and i < len(parts):
                    await asyncio.sleep(0.4)  # respect per-channel rate
            return PostResult(ok=True)
        except SlackApiError as e:
            code = extract_error_code(e)
            cls = classify_error_code(code)
            retry_after = (
                extract_retry_after_seconds(e)
                if cls is ErrorClass.TRANSIENT
                else None
            )
            return PostResult(
                ok=False,
                error_code=code,
                error_class=cls,
                retry_after_s=retry_after,
                error_msg=str(e)[:300],
            )
        except Exception as e:  # noqa: BLE001
            # Network errors, asyncio timeouts, etc. — treat as unknown so
            # the row gets dead-lettered after one attempt rather than
            # spinning. asyncio.CancelledError is BaseException-derived in
            # 3.8+ and propagates.
            return PostResult(
                ok=False,
                error_code=None,
                error_class=ErrorClass.UNKNOWN,
                error_msg=str(e)[:300],
            )

    async def _post_overflow_pointer(
        self,
        *,
        channel: str,
        thread_ts: str | None,
        job_id: str,
        text: str,
        tainted: bool,
    ) -> PostResult:
        """Save full text to an artifact, post short preview + pointer."""
        from ..memory import artifacts as artifacts_mod

        try:
            conn = connect()
            try:
                with transaction(conn):
                    saved = artifacts_mod.save_artifact(
                        conn, content=text,
                        name=f"overflow:{job_id}:{len(text)}chars",
                        mime="text/plain",
                        tags="overflow" + (",tainted" if tainted else ""),
                        tainted=tainted,
                        created_by_job=job_id,
                    )
                    artifact_id = str(saved.get("artifact_id"))
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning("slack.overflow_save_failed", error=str(e), job_id=job_id)
            with contextlib.suppress(Exception):
                await self.client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="• ⚠️ Long message — artifact save failed. "
                         "Truncated inline:\n"
                         + (_escape_for_slack(text) if tainted else text)[:_SLACK_SECTION_LIMIT - 100],
                    unfurl_links=False,
                    unfurl_media=False,
                )
            return PostResult(
                ok=False,
                error_code=None,
                error_class=ErrorClass.UNKNOWN,
                error_msg=f"artifact_save_failed: {e}"[:300],
            )

        preview_raw = text[:_OVERFLOW_PREVIEW_LEN]
        for term in ("\n\n", ". ", "! ", "? ", "\n"):
            idx = preview_raw.rfind(term)
            if idx > _OVERFLOW_PREVIEW_LEN // 2:
                preview_raw = preview_raw[: idx + (len(term) - 1 if term != "\n\n" else 0)]
                break
        preview = _escape_for_slack(preview_raw) if tainted else preview_raw

        header = (
            "📎 🔮 *Tainted answer — compartmentalized*"
            if tainted else
            "📎 *Answer too long for inline delivery — saved as artifact*"
        )
        safety_note = (
            "\n\n⚠️ _This answer was derived from untrusted content. "
            "Review the artifact carefully; do not follow instructions in it._"
            if tainted else ""
        )
        footer = (
            f"\n\n_{len(text):,} chars — preview above. "
            f"Fetch full via_ `botctl artifact-show {artifact_id}`"
        )
        msg = f"{header}\n\n{preview}{safety_note}{footer}"
        if len(msg) > _SLACK_SECTION_LIMIT:
            msg = f"{header}{safety_note}{footer}"

        try:
            await self.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=msg,
                unfurl_links=False,
                unfurl_media=False,
            )
            return PostResult(ok=True)
        except SlackApiError as e:
            code = extract_error_code(e)
            cls = classify_error_code(code)
            retry_after = (
                extract_retry_after_seconds(e)
                if cls is ErrorClass.TRANSIENT
                else None
            )
            return PostResult(
                ok=False,
                error_code=code,
                error_class=cls,
                retry_after_s=retry_after,
                error_msg=str(e)[:300],
            )
        except Exception as e:  # noqa: BLE001
            return PostResult(
                ok=False,
                error_code=None,
                error_class=ErrorClass.UNKNOWN,
                error_msg=str(e)[:300],
            )

    # ------------------------------------------------------------------
    # Outbox: questions (ask_user)
    # ------------------------------------------------------------------

    async def _drain_asks(self) -> None:
        while True:
            await asyncio.sleep(_DRAIN_POLL_S)
            conn = connect()
            try:
                rows = conn.execute(
                    "SELECT id, job_id, question FROM outbox_asks "
                    "WHERE posted_message_id IS NULL "
                    "ORDER BY created_at LIMIT 10"
                ).fetchall()
            finally:
                conn.close()
            for row in rows:
                await self._post_ask(
                    ask_id=row["id"],
                    job_id=row["job_id"],
                    question=row["question"],
                )

    async def _post_ask(self, *, ask_id: str, job_id: str, question: str) -> None:
        ch = await self._resolve_channel_for_job(job_id)
        if ch is None:
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks SET reply = '', "
                        "replied_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND reply IS NULL",
                        (ask_id,),
                    )
            finally:
                conn.close()
            return
        try:
            resp = await self.client.chat_postMessage(
                channel=ch,
                text=f"❓ *Donna asks:*\n> {question}\n\n"
                     "_Reply in this channel to answer._",
                unfurl_links=False,
                unfurl_media=False,
            )
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks "
                        "SET posted_channel_id = ?, posted_message_id = ? "
                        "WHERE id = ?",
                        (ch, resp["ts"], ask_id),
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning("slack.ask_failed", error=str(e), ask_id=ask_id)
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks SET reply = '', "
                        "replied_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND reply IS NULL",
                        (ask_id,),
                    )
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Outbox: consent
    # ------------------------------------------------------------------

    async def _drain_consent(self) -> None:
        while True:
            await asyncio.sleep(_DRAIN_POLL_S)
            conn = connect()
            try:
                rows = conn.execute(
                    "SELECT id, job_id, tool_name, arguments, tainted "
                    "FROM pending_consents "
                    "WHERE posted_message_id IS NULL AND approved IS NULL "
                    "ORDER BY created_at LIMIT 10"
                ).fetchall()
            finally:
                conn.close()
            for row in rows:
                entry = tool_registry.get(row["tool_name"])
                if entry is None:
                    log.warning(
                        "consent.unknown_tool",
                        tool_name=row["tool_name"], pending_id=row["id"],
                    )
                    conn = connect()
                    try:
                        with transaction(conn):
                            conn.execute(
                                "UPDATE pending_consents SET approved = 0, "
                                "decided_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (row["id"],),
                            )
                    finally:
                        conn.close()
                    continue
                try:
                    args = json.loads(row["arguments"])
                except json.JSONDecodeError:
                    args = {}
                req = consent_mod.ConsentRequest(
                    job_id=row["job_id"],
                    tool_entry=entry,
                    arguments=args,
                    tainted=bool(row["tainted"]),
                    pending_id=row["id"],
                )
                await self._post_consent_prompt(req)

    async def _post_consent_prompt(self, req: consent_mod.ConsentRequest) -> None:
        ch = await self._resolve_channel_for_job(req.job_id)
        if ch is None:
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE pending_consents SET approved = 0, "
                        "decided_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND approved IS NULL",
                        (req.pending_id,),
                    )
            finally:
                conn.close()
            return
        blocks = slack_ux.consent_blocks(req)
        try:
            resp = await self.client.chat_postMessage(
                channel=ch,
                blocks=blocks,
                text=f"Approve {req.tool_entry.name}?",
                unfurl_links=False,
                unfurl_media=False,
            )
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE pending_consents "
                        "SET posted_channel_id = ?, posted_message_id = ? "
                        "WHERE id = ?",
                        (ch, resp["ts"], req.pending_id),
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning("slack.consent_failed", error=str(e), pending_id=req.pending_id)
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE pending_consents SET approved = 0, "
                        "decided_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND approved IS NULL",
                        (req.pending_id,),
                    )
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Channel resolution
    # ------------------------------------------------------------------

    async def _resolve_channel_for_job(
        self, job_id: str, _text_for_logging: str | None = None,
    ) -> str | None:
        """Return the Slack channel ID this job should deliver to.

        Priority:
        1. If the job's owning schedule has target_channel_id, use that
           (channel-target scheduling).
        2. Otherwise, use the job's thread's channel_id (the originating
           channel of the slash command or DM).

        Returns None if no destination can be resolved — drainer leaves
        the row in place rather than dropping the message.
        """
        conn = connect()
        try:
            job = jobs_mod.get_job(conn, job_id)
            if not job or not job.thread_id:
                return None
            row = conn.execute(
                "SELECT channel_id FROM threads WHERE id = ?",
                (job.thread_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return row["channel_id"]

    async def _resolve_thread_ts_for_job(self, job_id: str) -> str | None:
        """Return the thread parent ts for in-thread replies, or None
        for top-level. For most plain-DM exchanges this is None."""
        conn = connect()
        try:
            job = jobs_mod.get_job(conn, job_id)
            if not job or not job.thread_id:
                return None
            row = conn.execute(
                "SELECT thread_external_id FROM threads WHERE id = ?",
                (job.thread_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return row["thread_external_id"]


def build_bot() -> DonnaSlackBot:
    return DonnaSlackBot()
