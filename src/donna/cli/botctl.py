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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..config import settings
from ..memory import cost as cost_mod
from ..memory import jobs as jobs_mod
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


def _parse_since(s: str) -> timedelta | None:
    """Parse '1d' / '3h' / '30m' / '1w' into a timedelta. Returns None on 'all'."""
    if not s or s == "all":
        return None
    unit = s[-1].lower()
    try:
        qty = int(s[:-1] or "1")
    except ValueError:
        return None
    factor = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}.get(unit)
    if factor is None:
        return None
    return timedelta(**{factor: qty})


def _pretty_task(task: str, mode: str) -> str:
    """Render a job's task for the `jobs` table. Debate-mode tasks are JSON
    payloads (`{"scope_a": "...", "scope_b": "...", "topic": "..."}`) which
    look hideous when truncated mid-quoted-key at char 60. Render them as
    'scope_a vs scope_b: topic' instead. All other modes use the task
    verbatim, truncated."""
    if mode == "debate" and task.strip().startswith("{"):
        try:
            payload = json.loads(task)
        except json.JSONDecodeError:
            return task[:60]
        if not isinstance(payload, dict):
            return task[:60]
        scopes = [
            payload.get(k)
            for k in ("scope_a", "scope_b", "scope_c", "scope_d")
            if payload.get(k)
        ]
        topic = payload.get("topic", "")
        parts = []
        if scopes:
            parts.append(" vs ".join(str(s) for s in scopes))
        if topic:
            parts.append(f": {topic}")
        rendered = "".join(parts) or task
        return rendered[:60]
    return task[:60]


@app.command()
def jobs(
    since: str = typer.Option("1d", help="'30m' | '3h' | '1d' | '1w' | 'all'"),
    limit: int = 25,
) -> None:
    """Recent jobs (newest first), optionally filtered by `--since`."""
    window = _parse_since(since)
    conn = connect()
    try:
        rows = jobs_mod.recent_jobs(conn, limit=limit, since=window)
    finally:
        conn.close()
    t = Table("id", "status", "mode", "scope", "tools", "$", "tainted", "task")
    for j in rows:
        t.add_row(
            j.id, j.status.value, j.mode.value, j.agent_scope,
            str(j.tool_call_count), f"${j.cost_usd:.2f}",
            "⚠️ " if j.tainted else "",
            _pretty_task(j.task, j.mode.value),
        )
    console.print(t)


def _resolve_job(conn, id_or_prefix: str):
    """Look up a job by full id, else by unique prefix. Returns (job, actual_id)."""
    j = jobs_mod.get_job(conn, id_or_prefix)
    if j:
        return j, id_or_prefix
    # fallback: prefix match — unambiguous only
    rows = conn.execute(
        "SELECT id FROM jobs WHERE id LIKE ? LIMIT 2", (f"{id_or_prefix}%",)
    ).fetchall()
    if len(rows) == 1:
        full = rows[0]["id"]
        return jobs_mod.get_job(conn, full), full
    if len(rows) > 1:
        console.print(f"[yellow]prefix '{id_or_prefix}' is ambiguous — matches multiple jobs[/yellow]")
    return None, id_or_prefix


@app.command()
def job(job_id: str) -> None:
    """Inspect one job: metadata + its tool calls. Accepts a unique id prefix."""
    conn = connect()
    try:
        j, resolved = _resolve_job(conn, job_id)
        calls = tool_calls_mod.tool_calls_for(conn, resolved) if j else []
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
def cache_hit_rate(since: str = typer.Option("1d", "--since", help="1h, 1d, 7d")) -> None:
    """Show Anthropic prompt cache hit rate — is caching actually working?"""
    # crude time parsing
    unit = since[-1]
    qty = int(since[:-1] or "1")
    sql_window = {
        "h": f"-{qty} hours", "d": f"-{qty} days", "m": f"-{qty} minutes",
    }.get(unit, "-1 days")

    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT
              SUM(input_tokens) AS input_sum,
              SUM(cache_read_tokens) AS cache_read_sum,
              SUM(cache_write_tokens) AS cache_write_sum,
              SUM(output_tokens) AS output_sum,
              SUM(cost_usd) AS cost_sum,
              COUNT(*) AS n
            FROM cost_ledger
            WHERE kind = 'llm' AND created_at >= datetime('now', ?)
            """,
            (sql_window,),
        ).fetchone()
    finally:
        conn.close()

    input_tok = int(row["input_sum"] or 0)
    cache_read = int(row["cache_read_sum"] or 0)
    cache_write = int(row["cache_write_sum"] or 0)
    output_tok = int(row["output_sum"] or 0)
    cost = float(row["cost_sum"] or 0.0)
    n = int(row["n"] or 0)

    # "Hit rate" = what fraction of input tokens were served from cache
    total_input = input_tok + cache_read
    hit_rate = (cache_read / total_input * 100) if total_input else 0.0

    t = Table("window", "calls", "input_tok", "cache_read", "cache_write", "output_tok", "hit %", "$")
    t.add_row(
        since, str(n), f"{input_tok:,}", f"{cache_read:,}", f"{cache_write:,}",
        f"{output_tok:,}", f"{hit_rate:.1f}%", f"${cost:.4f}",
    )
    console.print(t)
    if n == 0:
        console.print("[yellow]No LLM calls recorded in this window — nothing to measure yet.[/yellow]")
    elif hit_rate < 10:
        console.print("[yellow]Low cache hit rate — check prompt composition ordering.[/yellow]")
    else:
        console.print(f"[green]Cache working — saving ~{cache_read:,} input tokens in this window.[/green]")


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
            raise typer.Exit(1) from e
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


@app.command("forget-artifact")
def forget_artifact(
    artifact_id: str,
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip interactive confirmation",
    ),
) -> None:
    """Delete an artifact row and its blob file.

    Fills the gap flagged in KNOWN_ISSUES / SESSION_RESUME — the previous
    recipe was hand-rolled SQL + `rm`.

    The `artifacts.sha256` column is UNIQUE, so rows are always 1:1 with
    blob files. We warn (but don't block) when a `knowledge_sources.source_ref`
    points at this artifact — those references are free-form text, so a
    dangling one is weird but not catastrophic.
    """
    import os

    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, sha256, name, mime, bytes, tainted FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        console.print(f"[red]artifact {artifact_id} not found[/red]")
        raise typer.Exit(1)

    conn = connect()
    try:
        ks_refs = conn.execute(
            "SELECT id, title FROM knowledge_sources WHERE source_ref = ?",
            (artifact_id,),
        ).fetchall()
    finally:
        conn.close()

    blob_path = settings().artifacts_dir / f"{row['sha256']}.blob"

    console.print(f"[bold]{artifact_id}[/bold]  sha256={row['sha256'][:12]}…  "
                  f"bytes={row['bytes']}  mime={row['mime']}  "
                  f"tainted={'yes' if row['tainted'] else 'no'}")
    console.print(f"[dim]  blob at {blob_path}[/dim]")
    if ks_refs:
        console.print(f"[yellow]  ⚠️  referenced by {len(ks_refs)} knowledge_sources "
                      f"row(s); those source_refs will become dangling:[/yellow]")
        for r in ks_refs:
            console.print(f"    - {r['id']}: {r['title']}")

    if not force:
        confirmed = typer.confirm("Delete this artifact?", default=False)
        if not confirmed:
            console.print("[dim]aborted[/dim]")
            raise typer.Exit(0)

    conn = connect()
    try:
        with transaction(conn):
            conn.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))
    finally:
        conn.close()

    if blob_path.exists():
        try:
            os.remove(blob_path)
        except OSError as e:
            console.print(f"[yellow]  row deleted, but blob rm failed: {e}[/yellow]")

    console.print(f"🗑️  forgot artifact {artifact_id}")


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
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
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
