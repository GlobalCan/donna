"""Discord adapter — message intake, outbox drain, reaction approvals, slash commands.

- Intake: DMs + replies from the allowed user → insert a Job, reply with the job id
- Outbox: poll outbox_updates / outbox_asks / pending_consents tables; post into Discord
- Reactions: watch for ✅ / ❌ on consent messages; update pending_consents.approved
- Slash commands: /status /cancel /history /budget /teach /ask /speculate /debate /trace etc.

The outbox is DB-backed because donna.main and donna.worker are separate
processes; asyncio.Queue cannot cross that boundary (v0.2.0 bug surfaced in
Phase 1 live run, fixed by migration 0005 + this module).
"""
from __future__ import annotations

import asyncio
import json
import time

import discord
from discord import app_commands

from ..config import settings
from ..logging import get_logger
from ..memory import jobs as jobs_mod
from ..memory import threads as threads_mod
from ..memory.db import connect, transaction
from ..security import consent as consent_mod
from ..tools import registry as tool_registry
from . import discord_ux

log = get_logger(__name__)


# DB poll cadence for outbox drains. 1s feels instant in Discord.
_DRAIN_POLL_S = 1.0
# Per-job rate limit for progress updates. Matches prior behavior.
_UPDATE_RATE_LIMIT_S = 5.0


class DonnaBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True   # REQUIRES privileged intent enabled in dev portal
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    # -- lifecycle --
    async def setup_hook(self) -> None:
        discord_ux.register_commands(self)
        # If a guild id is given, sync there for fast propagation; else global
        gid = settings().discord_guild_id
        if gid:
            await self.tree.sync(guild=discord.Object(id=gid))
        else:
            await self.tree.sync()
        log.info("discord.setup_done")

        # Start outbox drainers — all three poll SQLite tables
        asyncio.create_task(self._drain_updates())
        asyncio.create_task(self._drain_consent())
        asyncio.create_task(self._drain_asks())

    async def on_ready(self) -> None:
        log.info(
            "discord.ready",
            user=str(self.user),
            user_id=self.user.id if self.user else None,
        )

    # -- message intake --
    async def on_message(self, message: discord.Message) -> None:
        if message.author.id == (self.user.id if self.user else 0):
            return
        if not self._is_allowed(message.author.id):
            return
        # Only respond in DMs or the thread we already own
        if message.guild is not None and not isinstance(message.channel, discord.Thread):
            return

        # H3: If this message is a reply to a pending ask in this channel,
        # bind it to that ask via DB update. Matches by channel (same as the
        # prior in-memory behavior) so any message in the channel where the
        # ask was posted is treated as the answer.
        incoming_channel_id = message.channel.id
        conn = connect()
        try:
            row = conn.execute(
                "SELECT id FROM outbox_asks "
                "WHERE posted_channel_id = ? AND reply IS NULL "
                "ORDER BY created_at LIMIT 1",
                (incoming_channel_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks SET reply = ?, replied_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND reply IS NULL",
                        (message.content, row["id"]),
                    )
            finally:
                conn.close()
            return

        # Otherwise, treat as a new task
        content = (message.content or "").strip()
        if not content:
            return
        await self._handle_new_task(message, content)

    async def _handle_new_task(self, message: discord.Message, content: str) -> None:
        # Create/get thread record
        conn = connect()
        try:
            with transaction(conn):
                thread_record_id = threads_mod.get_or_create_thread(
                    conn,
                    discord_channel=str(message.channel.id),
                    discord_thread=str(message.channel.id) if isinstance(message.channel, discord.Thread) else None,
                    title=content[:60],
                )
                threads_mod.insert_message(
                    conn, thread_id=thread_record_id, role="user", content=content,
                    discord_msg=str(message.id),
                )
                job_id = jobs_mod.insert_job(
                    conn, task=content, thread_id=thread_record_id,
                )
        finally:
            conn.close()

        await message.reply(
            f"📌 Job `{job_id[:18]}…` queued. I'll post updates in this channel."
        )

    # -- reactions --
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.user_id == (self.user.id if self.user else 0):
            return
        if not self._is_allowed(payload.user_id):
            return

        mid = payload.message_id
        emoji = str(payload.emoji)
        if emoji not in ("✅", "❌"):
            return

        approved = 1 if emoji == "✅" else 0
        conn = connect()
        try:
            with transaction(conn):
                # Only set approval if not already decided, and only for a row
                # whose Discord message matches. Prevents re-decision races.
                conn.execute(
                    "UPDATE pending_consents "
                    "SET approved = ?, decided_at = CURRENT_TIMESTAMP "
                    "WHERE posted_message_id = ? AND approved IS NULL",
                    (approved, mid),
                )
        finally:
            conn.close()

    # -- outbox drainers --------------------------------------------------
    async def _drain_updates(self) -> None:
        """Poll outbox_updates, post oldest first per job, DELETE after post."""
        last_sent: dict[str, float] = {}
        while True:
            await asyncio.sleep(_DRAIN_POLL_S)
            conn = connect()
            try:
                rows = conn.execute(
                    "SELECT id, job_id, text, tainted FROM outbox_updates "
                    "ORDER BY created_at LIMIT 50"
                ).fetchall()
            finally:
                conn.close()

            for row in rows:
                job_id = row["job_id"]
                now = time.time()
                wait = _UPDATE_RATE_LIMIT_S - (now - last_sent.get(job_id, 0.0))
                if wait > 0:
                    # Don't block the drainer on a single slow job — let other
                    # jobs' updates go through; we'll come back next poll.
                    continue
                posted = await self._post_update(
                    job_id=job_id, text=row["text"], tainted=bool(row["tainted"]),
                )
                if posted:
                    last_sent[job_id] = time.time()
                    conn = connect()
                    try:
                        with transaction(conn):
                            conn.execute(
                                "DELETE FROM outbox_updates WHERE id = ?",
                                (row["id"],),
                            )
                    finally:
                        conn.close()

    async def _drain_asks(self) -> None:
        """Poll outbox_asks for unposted rows, post, record posted_* ids.

        Replies are written by on_message; the worker polls for them.
        We do NOT delete rows here — the worker deletes after reading.
        """
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
                    ask_id=row["id"], job_id=row["job_id"], question=row["question"],
                )

    async def _drain_consent(self) -> None:
        """Poll pending_consents for undecided+unposted rows, post prompt."""
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
                        "consent.unknown_tool", tool_name=row["tool_name"],
                        pending_id=row["id"],
                    )
                    # Auto-decline: the tool vanished between queue and drain.
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

    async def _post_update(self, *, job_id: str, text: str, tainted: bool) -> bool:
        ch = await self._resolve_channel_for_job(job_id)
        if ch is None:
            return False
        prefix = "🔮 " if tainted else "• "
        try:
            await ch.send(f"{prefix}{text[:1500]}")
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("discord.update_failed", error=str(e), job_id=job_id)
            return False

    async def _post_ask(self, *, ask_id: str, job_id: str, question: str) -> None:
        ch = await self._resolve_channel_for_job(job_id)
        if ch is None:
            # Cannot resolve channel — abandon this ask.
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks SET reply = '', replied_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND reply IS NULL",
                        (ask_id,),
                    )
            finally:
                conn.close()
            return
        try:
            m = await ch.send(
                f"❓ **Donna asks:**\n> {question}\n\n_Reply in this channel to answer._"
            )
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks SET posted_channel_id = ?, posted_message_id = ? "
                        "WHERE id = ?",
                        (ch.id, m.id, ask_id),
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning("discord.ask_failed", error=str(e), ask_id=ask_id)
            # Can't display — abandon.
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE outbox_asks SET reply = '', replied_at = CURRENT_TIMESTAMP "
                        "WHERE id = ? AND reply IS NULL",
                        (ask_id,),
                    )
            finally:
                conn.close()

    async def _post_consent_prompt(self, req: consent_mod.ConsentRequest) -> None:
        ch = await self._resolve_channel_for_job(req.job_id)
        if ch is None:
            # Cannot display — auto-decline to unblock the worker.
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE pending_consents SET approved = 0, "
                        "decided_at = CURRENT_TIMESTAMP WHERE id = ? AND approved IS NULL",
                        (req.pending_id,),
                    )
            finally:
                conn.close()
            return
        embed = discord_ux.consent_embed(req)
        try:
            msg = await ch.send(embed=embed)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE pending_consents "
                        "SET posted_channel_id = ?, posted_message_id = ? "
                        "WHERE id = ?",
                        (ch.id, msg.id, req.pending_id),
                    )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.warning("discord.consent_failed", error=str(e), pending_id=req.pending_id)
            conn = connect()
            try:
                with transaction(conn):
                    conn.execute(
                        "UPDATE pending_consents SET approved = 0, "
                        "decided_at = CURRENT_TIMESTAMP WHERE id = ? AND approved IS NULL",
                        (req.pending_id,),
                    )
            finally:
                conn.close()

    async def _resolve_channel_for_job(self, job_id: str) -> discord.abc.Messageable | None:
        conn = connect()
        try:
            job = jobs_mod.get_job(conn, job_id)
        finally:
            conn.close()
        if not job or not job.thread_id:
            return None
        conn = connect()
        try:
            row = conn.execute(
                "SELECT discord_channel, discord_thread FROM threads WHERE id = ?",
                (job.thread_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        target_id = int(row["discord_thread"] or row["discord_channel"])
        ch = self.get_channel(target_id) or await self.fetch_channel(target_id)
        return ch  # type: ignore[return-value]

    # -- helpers --
    def _is_allowed(self, user_id: int) -> bool:
        return user_id == settings().discord_allowed_user_id


def build_bot() -> DonnaBot:
    return DonnaBot()
