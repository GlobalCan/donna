"""Discord UX — slash commands + embed templates."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from ..config import settings
from ..memory import cost as cost_mod
from ..memory import jobs as jobs_mod
from ..memory import prompts as prompts_mod
from ..memory import schedules as sched_mod
from ..memory.db import connect, transaction
from ..security import consent as consent_mod
from ..types import JobMode, JobStatus

if TYPE_CHECKING:
    from .discord_adapter import DonnaBot


def register_commands(bot: DonnaBot) -> None:
    tree = bot.tree

    @tree.command(name="status", description="Check a job's status")
    async def status_cmd(interaction: discord.Interaction, job_id: str) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        conn = connect()
        try:
            job = jobs_mod.get_job(conn, job_id)
        finally:
            conn.close()
        if not job:
            await interaction.response.send_message(f"no such job: {job_id}", ephemeral=True)
            return
        await interaction.response.send_message(embed=job_embed(job))

    @tree.command(name="cancel", description="Cancel a running job")
    async def cancel_cmd(interaction: discord.Interaction, job_id: str) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        conn = connect()
        try:
            with transaction(conn):
                jobs_mod.set_status(conn, job_id, JobStatus.CANCELLED)
        finally:
            conn.close()
        await interaction.response.send_message(f"cancelled `{job_id[:20]}`")

    @tree.command(name="history", description="Recent jobs")
    async def history_cmd(interaction: discord.Interaction, limit: int = 10) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        conn = connect()
        try:
            jobs = jobs_mod.recent_jobs(conn, limit=limit)
        finally:
            conn.close()
        lines = [f"• `{j.id[:18]}` [{j.status.value}] {j.task[:80]}" for j in jobs]
        await interaction.response.send_message("\n".join(lines) or "no jobs yet")

    @tree.command(name="budget", description="Today's spend")
    async def budget_cmd(interaction: discord.Interaction) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        conn = connect()
        try:
            spent = cost_mod.spend_today(conn)
        finally:
            conn.close()
        thresholds = settings().budget_thresholds
        await interaction.response.send_message(
            f"💰 Spent today: **${spent:.2f}** · alerts at: " +
            ", ".join(f"${t:.0f}" for t in thresholds)
        )

    @tree.command(name="ask", description="Ask a scoped agent a grounded question")
    async def ask_cmd(interaction: discord.Interaction, scope: str, question: str) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        await _enqueue_scoped(interaction, scope=scope, task=question, mode=JobMode.GROUNDED)

    @tree.command(name="speculate", description="Speculate in a scope's voice (opt-in)")
    async def speculate_cmd(interaction: discord.Interaction, scope: str, question: str) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        await _enqueue_scoped(interaction, scope=scope, task=question, mode=JobMode.SPECULATIVE)

    @tree.command(name="debate", description="Debate scope_a vs scope_b on a topic")
    async def debate_cmd(
        interaction: discord.Interaction, scope_a: str, scope_b: str, topic: str, rounds: int = 3,
    ) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        task = json.dumps({"scope_a": scope_a, "scope_b": scope_b, "topic": topic, "rounds": rounds})
        await _enqueue_scoped(interaction, scope="orchestrator", task=task, mode=JobMode.DEBATE)

    @tree.command(name="schedule", description="Add a cron schedule (UTC)")
    async def schedule_cmd(interaction: discord.Interaction, cron_expr: str, task: str) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        # Capture the current Discord channel/thread so when this schedule
        # fires the worker's finalize/outbox path can deliver the reply
        # back to where `/schedule` was invoked. Without this the job
        # runs to status=done but `_resolve_channel_for_job` returns
        # None and the reply sits undeliverable in `outbox_updates`.
        # Bug surfaced during the first live smoke test 2026-04-30.
        from ..memory import threads as threads_mod
        try:
            conn = connect()
            try:
                with transaction(conn):
                    thread_id = threads_mod.get_or_create_thread(
                        conn,
                        discord_channel=str(interaction.channel_id),
                        discord_thread=(
                            str(interaction.channel_id)
                            if isinstance(interaction.channel, discord.Thread)
                            else None
                        ),
                    )
                    sid = sched_mod.insert_schedule(
                        conn, cron_expr=cron_expr, task=task,
                        thread_id=thread_id,
                    )
                # Re-read so we can show the operator the next_run_at
                # (croniter computes it inside insert_schedule). Confirms
                # the cron expression parsed and gives a concrete next-fire
                # time so the operator knows when to look for the result.
                row = conn.execute(
                    "SELECT next_run_at FROM schedules WHERE id = ?", (sid,),
                ).fetchone()
            finally:
                conn.close()
        except ValueError as e:
            # The most common error here is forgetting spaces between
            # cron fields (e.g. typing `*****` instead of `* * * * *`).
            # Surface that explicitly so the operator doesn't have to
            # guess at croniter's terse `Invalid cron expression: *****`.
            stripped = cron_expr.strip()
            hint = ""
            if stripped and " " not in stripped:
                hint = (
                    "\n\n_Hint: cron needs **5 space-separated fields** "
                    "(minute hour day month dayOfWeek). Example: "
                    "`* * * * *` for every minute._"
                )
            await interaction.response.send_message(
                f"❌ invalid cron expression `{cron_expr}` — {e}{hint}",
                ephemeral=True,
            )
            return
        next_run = row["next_run_at"] if row else "?"
        await interaction.response.send_message(
            f"📅 scheduled `{sid}` — `{cron_expr}`\n"
            f"   next fire: **{next_run} UTC**\n"
            f"   task: {task[:200]}"
        )

    @tree.command(name="schedules", description="List active schedules")
    async def schedules_cmd(interaction: discord.Interaction) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        conn = connect()
        try:
            items = sched_mod.list_schedules(conn)
        finally:
            conn.close()
        if not items:
            await interaction.response.send_message(
                "no active schedules — add one with `/schedule cron_expr task`"
            )
            return
        lines = [f"**{len(items)} active schedule(s)**"]
        for s in items:
            last = s.get("last_run_at") or "never"
            lines.append(
                f"• `{s['id']}` `{s['cron_expr']}`\n"
                f"   next: {s['next_run_at']} UTC · last fired: {last}\n"
                f"   {s['task'][:120]}"
            )
        await interaction.response.send_message("\n".join(lines))

    @tree.command(name="heuristics", description="List a scope's heuristics")
    async def heuristics_cmd(interaction: discord.Interaction, scope: str) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        conn = connect()
        try:
            hs = prompts_mod.active_heuristics(conn, scope)
        finally:
            conn.close()
        await interaction.response.send_message(
            "\n".join(f"• {h}" for h in hs) or "(none active)"
        )

    @tree.command(name="approve_heuristic", description="Promote a heuristic to active")
    async def approve_h_cmd(interaction: discord.Interaction, heuristic_id: str) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        conn = connect()
        try:
            with transaction(conn):
                prompts_mod.approve_heuristic(conn, heuristic_id=heuristic_id)
        finally:
            conn.close()
        await interaction.response.send_message(f"✅ approved {heuristic_id}")

    @tree.command(name="model", description="Set the model tier for this conversation")
    @app_commands.choices(tier=[
        app_commands.Choice(name="fast (Haiku)",   value="fast"),
        app_commands.Choice(name="strong (Sonnet — default)", value="strong"),
        app_commands.Choice(name="heavy (Opus)",   value="heavy"),
        app_commands.Choice(name="clear override (use default)", value="clear"),
    ])
    async def model_cmd(
        interaction: discord.Interaction,
        tier: app_commands.Choice[str],
    ) -> None:
        """Pattern A Hermes steal #3: /model <tier> lets the user switch
        tier for this thread without touching env config. Override persists
        until explicitly cleared."""
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return

        from ..memory import threads as threads_mod

        channel_id = str(interaction.channel_id)
        conn = connect()
        try:
            with transaction(conn):
                thread_id = threads_mod.find_by_discord_channel(
                    conn, channel_id=channel_id,
                )
                if thread_id is None:
                    thread_id = threads_mod.get_or_create_thread(
                        conn,
                        discord_channel=channel_id,
                        discord_thread=(
                            channel_id
                            if isinstance(interaction.channel, discord.Thread)
                            else None
                        ),
                    )
                new_tier = None if tier.value == "clear" else tier.value
                threads_mod.set_model_tier_override(
                    conn, thread_id=thread_id, tier=new_tier,
                )
        finally:
            conn.close()

        if tier.value == "clear":
            msg = "🔄 Model override cleared — using default (strong/Sonnet)."
        else:
            msg = f"🎚 Model tier for this thread → **{tier.name}**. Jobs queued after this will use it."
        await interaction.response.send_message(msg)

    @tree.command(name="models", description="List available model runtimes")
    async def models_cmd(interaction: discord.Interaction) -> None:
        if not _allowed(interaction):
            await interaction.response.send_message("not authorized", ephemeral=True)
            return
        from ..memory import runtimes as rt_mod
        try:
            runtimes = rt_mod.list_runtimes()
        except Exception as e:
            await interaction.response.send_message(f"⚠ runtimes query failed: {e}", ephemeral=True)
            return
        if not runtimes:
            await interaction.response.send_message(
                "No runtimes registered. Run `alembic upgrade head`.",
                ephemeral=True,
            )
            return
        lines = ["**Registered model runtimes:**"]
        for r in runtimes:
            mark = "✓" if r.active else "×"
            lines.append(
                f"{mark} `{r.provider}:{r.tier}` → `{r.model_id}` "
                f"(in ${r.price_input}/Mtok, out ${r.price_output}/Mtok)"
            )
        await interaction.response.send_message("\n".join(lines))


async def _enqueue_scoped(
    interaction: discord.Interaction, *, scope: str, task: str, mode: JobMode,
) -> None:
    from ..memory import threads as threads_mod
    conn = connect()
    try:
        with transaction(conn):
            tid = threads_mod.get_or_create_thread(
                conn,
                discord_channel=str(interaction.channel_id),
                discord_thread=str(interaction.channel_id)
                    if isinstance(interaction.channel, discord.Thread) else None,
            )
            jid = jobs_mod.insert_job(
                conn, task=task, agent_scope=scope, mode=mode, thread_id=tid,
            )
    finally:
        conn.close()
    await interaction.response.send_message(
        f"📌 Job `{jid[:18]}…` queued · scope `{scope}` · mode `{mode.value}`"
    )


def _allowed(interaction: discord.Interaction) -> bool:
    return interaction.user.id == settings().discord_allowed_user_id


# ---------- Embed templates ------------------------------------------------


def job_embed(job) -> discord.Embed:
    color = {
        "queued": 0x808080,
        "running": 0x3498DB,
        "paused_awaiting_consent": 0xF1C40F,
        "done": 0x2ECC71,
        "failed": 0xE74C3C,
        "cancelled": 0x95A5A6,
    }.get(job.status.value, 0x7F8C8D)
    e = discord.Embed(title=f"Job {job.id[:18]}…", color=color)
    e.add_field(name="Status", value=job.status.value, inline=True)
    e.add_field(name="Mode", value=job.mode.value, inline=True)
    e.add_field(name="Scope", value=job.agent_scope, inline=True)
    e.add_field(name="Tool calls", value=str(job.tool_call_count), inline=True)
    e.add_field(name="Cost", value=f"${job.cost_usd:.2f}", inline=True)
    e.add_field(name="Tainted", value="yes" if job.tainted else "no", inline=True)
    e.add_field(name="Task", value=job.task[:500], inline=False)
    if job.error:
        e.add_field(name="Error", value=job.error[:500], inline=False)
    return e


def consent_embed(req: consent_mod.ConsentRequest) -> discord.Embed:
    color = 0xE74C3C if req.tainted else 0xF1C40F
    e = discord.Embed(
        title=f"⚠️ Approve {req.tool_entry.name}?",
        description=f"Job `{req.job_id[:18]}…`",
        color=color,
    )
    e.add_field(name="Tool", value=f"`{req.tool_entry.name}`", inline=True)
    e.add_field(name="Scope", value=req.tool_entry.scope, inline=True)
    e.add_field(name="Cost tier", value=req.tool_entry.cost, inline=True)
    e.add_field(name="Tainted ctx", value="yes" if req.tainted else "no", inline=True)
    args_summary = json.dumps(req.arguments, default=str)[:800]
    e.add_field(name="Args", value=f"```json\n{args_summary}\n```", inline=False)
    e.set_footer(text="React ✅ to approve · ❌ to decline · timeout 30 min")
    return e
