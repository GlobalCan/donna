"""Discord adapter — message intake, outbox drain, reaction approvals, slash commands.

- Intake: DMs + replies from the allowed user → insert a Job, reply with the job id
- Outbox: drain ask_queue + update_queue + consent_queue; post into Discord
- Reactions: watch for ✅ / ❌ on consent/ask messages
- Slash commands: /status /cancel /history /budget /teach /ask /speculate /debate /trace etc.
"""
from __future__ import annotations

import asyncio
from typing import Any

import discord
from discord import app_commands

from ..config import settings
from ..logging import get_logger
from ..memory import jobs as jobs_mod
from ..memory import threads as threads_mod
from ..memory import cost as cost_mod
from ..memory.db import connect, transaction
from ..security import consent as consent_mod
from ..tools import communicate as comm
from ..types import JobMode, JobStatus
from . import discord_ux

log = get_logger(__name__)


class DonnaBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True   # REQUIRES privileged intent enabled in dev portal
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._pending_asks: dict[str, asyncio.Future[str]] = {}   # job_id -> reply future
        self._consent_msgs: dict[int, consent_mod.ConsentRequest] = {}  # message_id -> request
        self._ask_msgs: dict[int, comm.OutgoingAsk] = {}         # message_id -> ask

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

        # Start outbox drainers
        self.loop.create_task(self._drain_updates())
        self.loop.create_task(self._drain_consent())
        self.loop.create_task(self._drain_asks())

    async def on_ready(self) -> None:
        log.info("discord.ready", user=str(self.user), user_id=self.user.id if self.user else None)

    # -- message intake --
    async def on_message(self, message: discord.Message) -> None:
        if message.author.id == (self.user.id if self.user else 0):
            return
        if not self._is_allowed(message.author.id):
            return
        # Only respond in DMs or the thread we already own
        if message.guild is not None and not isinstance(message.channel, discord.Thread):
            return

        # H3: If this message is a reply to a pending ask, resolve it —
        # BUT only match asks that were posted in THIS channel/thread.
        incoming_channel_id = message.channel.id
        for mid, ask in list(self._ask_msgs.items()):
            if ask.future.done():
                self._ask_msgs.pop(mid, None)
                continue
            if ask.posted_channel_id == incoming_channel_id:
                ask.future.set_result(message.content)
                self._ask_msgs.pop(mid, None)
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

        if mid in self._consent_msgs:
            req = self._consent_msgs.pop(mid)
            if not req.future.done():
                req.future.set_result(emoji == "✅")

    # -- outbox drainers --
    async def _drain_updates(self) -> None:
        q = comm.update_queue()
        last_sent: dict[str, float] = {}
        while True:
            item = await q.get()
            # rate-limit 1/5s per job
            import time
            now = time.time()
            if now - last_sent.get(item.job_id, 0.0) < 5.0:
                await asyncio.sleep(5.0 - (now - last_sent.get(item.job_id, 0.0)))
            last_sent[item.job_id] = time.time()
            await self._post_update(item)

    async def _drain_consent(self) -> None:
        q = consent_mod.consent_queue()
        while True:
            req = await q.get()
            await self._post_consent_prompt(req)

    async def _drain_asks(self) -> None:
        q = comm.ask_queue()
        while True:
            req = await q.get()
            await self._post_ask(req)

    async def _post_update(self, item: comm.OutgoingUpdate) -> None:
        ch = await self._resolve_channel_for_job(item.job_id)
        if ch is None:
            return
        prefix = "🔮 " if item.tainted else "• "
        try:
            await ch.send(f"{prefix}{item.text[:1500]}")
        except Exception as e:  # noqa: BLE001
            log.warning("discord.update_failed", error=str(e))

    async def _post_ask(self, req: comm.OutgoingAsk) -> None:
        ch = await self._resolve_channel_for_job(req.job_id)
        if ch is None:
            req.future.set_result("")
            return
        try:
            m = await ch.send(
                f"❓ **Donna asks:**\n> {req.question}\n\n_Reply in this channel to answer._"
            )
            # H3: record where the ask was posted so reply matching is accurate
            req.posted_channel_id = ch.id
            self._ask_msgs[m.id] = req
        except Exception as e:  # noqa: BLE001
            log.warning("discord.ask_failed", error=str(e))
            req.future.set_result("")

    async def _post_consent_prompt(self, req: consent_mod.ConsentRequest) -> None:
        ch = await self._resolve_channel_for_job(req.job_id)
        if ch is None:
            req.future.set_result(False)
            return
        embed = discord_ux.consent_embed(req)
        try:
            msg = await ch.send(embed=embed)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            self._consent_msgs[msg.id] = req
        except Exception as e:  # noqa: BLE001
            log.warning("discord.consent_failed", error=str(e))
            req.future.set_result(False)

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
