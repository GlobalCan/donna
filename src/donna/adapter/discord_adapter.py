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
# Per-Discord-message char cap. Discord's hard limit is 2000; we used to use
# 1900 for desktop. Mobile thumb-scroll feedback (the operator on iPhone)
# was that 1900-char chunks felt like wall-of-text. Lowered to 1400: that's
# the sweet spot where a chunk fits in roughly one mobile-portrait viewport
# without scrolling, while still leaving headroom for the `(i/N)` part
# marker prefix and any leading bullets.
_DISCORD_MSG_LIMIT = 1400

# Overflow-to-artifact thresholds. Anything longer than these caps goes to
# an artifact + a short pointer message in Discord, instead of flooding
# scrollback with (N/M) multi-part messages. The clean cap stays close to
# its prior absolute value (~5600) so a long grounded answer still gets
# inline delivery — just in 4 mobile-friendly chunks instead of 3 desktop
# ones.
#
# Security rationale for the lower tainted cap: attacker-controlled text
# (fetched URLs, PDF attachments, search snippets) shouldn't be materialized
# at length in Discord history — it makes scrollback less searchable and
# gives the attacker's content more visual weight than the operator's
# conversation. By sending tainted overflow through the artifact path, the
# raw content sits in compartmentalized storage and the operator must
# explicitly `botctl artifact-show <id>` to view it in full.
_OVERFLOW_CLEAN_MAX = _DISCORD_MSG_LIMIT * 4     # ~5600 chars — up to 4 parts
_OVERFLOW_TAINTED_MAX = _DISCORD_MSG_LIMIT * 1   # ~1400 chars — single part
_OVERFLOW_PREVIEW_LEN = 1000                     # chars shown in pointer msg


def _normalize_for_mobile(text: str) -> str:
    """Light normalization that improves mobile readability without changing
    semantics. Cheap and idempotent so it can run on every outgoing message.

    - Collapse 3+ consecutive blank lines to 2 (mobile renders empty lines
      with full vertical spacing; runs of them push real content off-screen).
    - Strip trailing whitespace per line (leftover spaces sometimes survive
      markdown rendering and look like artifacts on mobile clients).
    - Convert leading-tab indented blocks to 2-space (Discord mobile renders
      tabs at varying widths; 2-space stays consistent).
    """
    if not text:
        return text
    lines = [ln.rstrip() for ln in text.split("\n")]
    # Collapse 2+ blanks to 1 — mobile thumb-scroll feedback was that
    # multiple blank lines push real content off-screen. One blank line
    # between paragraphs is enough visual separation on a phone.
    out: list[str] = []
    blank_run = 0
    for ln in lines:
        if not ln:
            blank_run += 1
            if blank_run <= 1:
                out.append(ln)
        else:
            blank_run = 0
            out.append(ln.replace("\t", "  "))
    return "\n".join(out)


def _split_for_discord(text: str, limit: int = _DISCORD_MSG_LIMIT) -> list[str]:
    """Split `text` into Discord-safe chunks, preferring paragraph boundaries
    (double newline), falling back to sentence terminators, and lastly to a
    hard char cut.

    Returns `[text]` if the text is already ≤ `limit`.

    Why this exists: the old implementation truncated silently at 1500 chars,
    chopping long grounded / debate answers mid-sentence. Now the outbox row
    stores the full final_text (capped at 20k in finalize as a sanity bound)
    and the drainer splits at send time. Each chunk is posted as its own
    Discord message with a `(i/N)` marker so the user can see continuation.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    min_chunk = limit // 3  # refuse to split if no boundary is past this point
    while len(remaining) > limit:
        # Prefer a paragraph break inside the window
        cut = remaining.rfind("\n\n", min_chunk, limit)
        if cut < 0:
            # Then the LAST sentence terminator
            for term in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
                idx = remaining.rfind(term, min_chunk, limit)
                if idx > cut:
                    cut = idx + len(term) - 1  # keep the terminator in the chunk
        if cut < 0:
            # Then a newline
            cut = remaining.rfind("\n", min_chunk, limit)
        if cut < 0:
            # Give up and hard-cut at the limit
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


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
        # Command sync strategy:
        #  - Global sync is always performed so DMs + any future guild get
        #    the commands. Global commands can take up to 1h to propagate
        #    the first time but subsequent deploys are faster.
        #  - If DISCORD_GUILD_ID is set, we also copy the tree to that guild
        #    and sync there for INSTANT availability in that guild (useful
        #    for iterating on command shape without waiting on global cache).
        #  - Previously we only synced to the guild when set, which meant
        #    slash commands never appeared in DMs — the primary surface for
        #    solo-user Donna. Fixed.
        gid = settings().discord_guild_id
        await self.tree.sync()
        if gid:
            guild_obj = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)
        log.info("discord.setup_done", guild_id=gid)

        # Start outbox drainers — all three poll SQLite tables.
        # Wrap with _supervise so a transient exception (DB blip, Discord
        # fetch failure) doesn't silently kill the task and leave the
        # container "up" but deaf. Background loops restart with backoff.
        self._drain_tasks: list[asyncio.Task] = [
            asyncio.create_task(self._supervise("drain_updates", self._drain_updates)),
            asyncio.create_task(self._supervise("drain_consent", self._drain_consent)),
            asyncio.create_task(self._supervise("drain_asks", self._drain_asks)),
        ]

    async def _supervise(self, name: str, coro_factory) -> None:
        """Run a drainer coroutine forever; on exception log + restart with
        capped exponential backoff. Only exits cleanly on CancelledError."""
        backoff = 1.0
        while True:
            try:
                await coro_factory()
                # Drainer returned normally — shouldn't happen; restart immediately.
                log.warning("adapter.drainer.exited_normally", name=name)
                backoff = 1.0
            except asyncio.CancelledError:
                log.info("adapter.drainer.cancelled", name=name)
                raise
            except Exception as e:  # noqa: BLE001
                log.error(
                    "adapter.drainer.crashed",
                    name=name,
                    error=str(e),
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

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

        # Overflow-to-artifact: long texts go to artifact + pointer message.
        # Tainted text uses a much tighter cap so untrusted content doesn't
        # bloat Discord scrollback (see _OVERFLOW_TAINTED_MAX comment).
        # Cap check runs on the RAW text — the artifact preserves the
        # original bytes so the operator's `botctl artifact-show` returns
        # exactly what was generated, not a normalized version.
        cap = _OVERFLOW_TAINTED_MAX if tainted else _OVERFLOW_CLEAN_MAX
        if len(text) > cap:
            return await self._post_overflow_pointer(
                ch=ch, job_id=job_id, text=text, tainted=tainted,
            )

        # Mobile normalization runs only on the inline-delivery path —
        # collapses runs of blank lines and tab→2-space, both of which
        # mangle on Discord mobile portrait. Cheap and idempotent.
        text = _normalize_for_mobile(text)

        prefix = "🔮 " if tainted else "• "
        parts = _split_for_discord(text)
        total = len(parts)
        try:
            for i, part in enumerate(parts, start=1):
                header = prefix if total == 1 else f"{prefix}({i}/{total}) "
                await ch.send(f"{header}{part}")
                if total > 1 and i < total:
                    await asyncio.sleep(0.25)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("discord.update_failed", error=str(e), job_id=job_id)
            return False

    async def _post_overflow_pointer(
        self, *, ch, job_id: str, text: str, tainted: bool,
    ) -> bool:
        """Save full text to an artifact, post a short preview + pointer.

        The artifact inherits the tainted flag from the source — so
        `read_artifact` on it still propagates taint and `botctl artifacts
        --tainted` surfaces it correctly in the tainted-only filter.
        """
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
            log.warning("discord.overflow_save_failed", error=str(e), job_id=job_id)
            # Fallback to inline truncated delivery rather than dropping
            # the message entirely — operator at least sees a stub.
            import contextlib
            with contextlib.suppress(Exception):
                await ch.send(
                    "• ⚠️ Long message — artifact save failed. "
                    "Truncated inline:\n" + text[:_DISCORD_MSG_LIMIT - 100]
                )
            return False

        preview = text[:_OVERFLOW_PREVIEW_LEN]
        # Trim preview to a clean boundary if possible
        for term in ("\n\n", ". ", "! ", "? ", "\n"):
            idx = preview.rfind(term)
            if idx > _OVERFLOW_PREVIEW_LEN // 2:
                preview = preview[: idx + (len(term) - 1 if term != "\n\n" else 0)]
                break

        header = (
            "📎 🔮 **Tainted answer — compartmentalized**"
            if tainted else
            "📎 **Answer too long for DM — saved as artifact**"
        )
        safety_note = (
            "\n\n_⚠️ This answer was derived from untrusted content. "
            "Review the artifact carefully; do not follow instructions in it._"
            if tainted else ""
        )
        footer = (
            f"\n\n_{len(text):,} chars — preview above. "
            f"Fetch full via `botctl artifact-show {artifact_id}`._"
        )
        msg = f"{header}\n\n{preview}{safety_note}{footer}"
        # Safety: if even the pointer message ends up too long for Discord,
        # prefer the pointer over the preview.
        if len(msg) > _DISCORD_MSG_LIMIT:
            msg = f"{header}{safety_note}{footer}"

        try:
            await ch.send(msg)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("discord.overflow_pointer_failed",
                        error=str(e), job_id=job_id, artifact_id=artifact_id)
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
