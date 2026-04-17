"""botctl — Typer CLI for Donna ops.

  botctl jobs --since 1d
  botctl job <id>
  botctl cost --today
  botctl teach <scope> <path>
  botctl schedule add "0 8 * * *" "morning brief"
  botctl schedule list
  botctl heuristics <scope>
  botctl traces prune --older-than 30d
  botctl migrate
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..config import settings
from ..memory import jobs as jobs_mod
from ..memory import cost as cost_mod
from ..memory import prompts as prompts_mod
from ..memory import schedules as sched_mod
from ..memory import tool_calls as tool_calls_mod
from ..memory.db import connect, transaction

app = typer.Typer(help="Donna ops CLI")
schedule_app = typer.Typer(help="Schedule management")
traces_app = typer.Typer(help="Trace / log management")
app.add_typer(schedule_app, name="schedule")
app.add_typer(traces_app, name="traces")

console = Console()


@app.command()
def jobs(since: str = typer.Option("1d", help="'1d', '1h', or '30m'"), limit: int = 25) -> None:
    """Recent jobs."""
    conn = connect()
    try:
        rows = jobs_mod.recent_jobs(conn, limit=limit)
    finally:
        conn.close()
    t = Table("id", "status", "mode", "scope", "tools", "$", "tainted", "task")
    for j in rows:
        t.add_row(
            j.id[:18], j.status.value, j.mode.value, j.agent_scope,
            str(j.tool_call_count), f"${j.cost_usd:.2f}",
            "⚠️ " if j.tainted else "",
            j.task[:60],
        )
    console.print(t)


@app.command()
def job(job_id: str) -> None:
    """Inspect one job: metadata + its tool calls."""
    conn = connect()
    try:
        j = jobs_mod.get_job(conn, job_id)
        calls = tool_calls_mod.tool_calls_for(conn, job_id)
    finally:
        conn.close()
    if not j:
        console.print(f"[red]job {job_id} not found[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{j.id}[/bold]  status={j.status.value}  mode={j.mode.value}  scope={j.agent_scope}")
    console.print(f"tainted={'yes' if j.tainted else 'no'}  cost=${j.cost_usd:.4f}  tool_calls={j.tool_call_count}")
    console.print(f"task: {j.task}")
    if j.error:
        console.print(f"[red]error: {j.error}[/red]")
    console.print()
    t = Table("n", "tool", "status", "ms", "$", "tainted")
    for i, c in enumerate(calls, 1):
        t.add_row(
            str(i), c["tool_name"], c["status"],
            str(c["duration_ms"]), f"${c['cost_usd']:.4f}",
            "⚠️" if c["tainted"] else "",
        )
    console.print(t)


@app.command()
def cost(today: bool = True) -> None:
    """Daily cost."""
    conn = connect()
    try:
        spent = cost_mod.spend_today(conn)
    finally:
        conn.close()
    console.print(f"💰 [bold]${spent:.4f}[/bold] spent today")


@app.command()
def teach(
    scope: str,
    path: str,
    source_type: str = typer.Option("other"),
    title: str = typer.Option(""),
    copyright_status: str = typer.Option("personal_use"),
    publication_date: str = typer.Option(""),
) -> None:
    """Ingest a file into a scope's corpus."""
    from ..ingest.pipeline import ingest_text

    p = Path(path)
    if not p.exists():
        console.print(f"[red]file not found: {path}[/red]")
        raise typer.Exit(1)
    if p.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            text = "\n\n".join((page.extract_text() or "") for page in PdfReader(str(p)).pages)
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]pdf extraction failed: {e}[/red]")
            raise typer.Exit(1)
    else:
        text = p.read_text(encoding="utf-8", errors="replace")

    async def go() -> None:
        result = await ingest_text(
            scope=scope, source_type=source_type, title=title or p.stem,
            content=text, copyright_status=copyright_status,
            publication_date=publication_date or None,
            added_by="botctl:teach",
        )
        console.print(json.dumps(result, indent=2))

    asyncio.run(go())


@app.command()
def heuristics(scope: str) -> None:
    conn = connect()
    try:
        active = prompts_mod.active_heuristics(conn, scope)
        all_rows = conn.execute(
            "SELECT id, status, heuristic FROM agent_heuristics WHERE agent_scope = ? ORDER BY created_at",
            (scope,),
        ).fetchall()
    finally:
        conn.close()
    console.print(f"[bold]{scope}[/bold] — {len(active)} active / {len(all_rows)} total")
    for r in all_rows:
        badge = "✅" if r["status"] == "active" else ("💭" if r["status"] == "proposed" else "🗑️")
        console.print(f"  {badge} [{r['id']}] {r['heuristic']}")


@app.command()
def migrate() -> None:
    """Run alembic upgrade head."""
    import subprocess
    settings().data_dir.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["alembic", "upgrade", "head"])


# ---- schedule ---------------------------------------------------------------


@schedule_app.command("add")
def schedule_add(cron_expr: str, task: str, agent_scope: str = "orchestrator") -> None:
    conn = connect()
    try:
        with transaction(conn):
            sid = sched_mod.insert_schedule(
                conn, cron_expr=cron_expr, task=task, agent_scope=agent_scope,
            )
    finally:
        conn.close()
    console.print(f"📅 scheduled [bold]{sid}[/bold] — `{cron_expr}`")


@schedule_app.command("list")
def schedule_list() -> None:
    conn = connect()
    try:
        items = sched_mod.list_schedules(conn)
    finally:
        conn.close()
    t = Table("id", "cron", "next_run", "task")
    for s in items:
        t.add_row(s["id"], s["cron_expr"], str(s["next_run_at"]), s["task"][:60])
    console.print(t)


@schedule_app.command("disable")
def schedule_disable(sid: str) -> None:
    conn = connect()
    try:
        with transaction(conn):
            sched_mod.disable_schedule(conn, sid)
    finally:
        conn.close()
    console.print(f"🔕 disabled {sid}")


# ---- traces -----------------------------------------------------------------


@traces_app.command("prune")
def traces_prune(older_than_days: int = typer.Option(30, "--older-than-days")) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    conn = connect()
    try:
        with transaction(conn):
            n = conn.execute(
                "DELETE FROM traces WHERE started_at < ?", (cutoff,)
            ).rowcount
    finally:
        conn.close()
    console.print(f"🗑️  pruned {n} trace rows older than {older_than_days}d")


if __name__ == "__main__":
    app()
