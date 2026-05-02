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
heuristics_app = typer.Typer(help="Heuristic management: list / approve / retire")
dead_letter_app = typer.Typer(
    help=(
        "outbox_dead_letter ops: list / show / retry / discard. "
        "Shows rows the v0.5.1 Slack drainer routed off the live "
        "outbox after terminal/unknown delivery errors."
    ),
)
async_tasks_app = typer.Typer(
    help=(
        "async_tasks ops: list / show. v0.6 supervised work queue "
        "(safe_summary backfill, future morning brief etc.)."
    ),
)
retention_app = typer.Typer(
    help=(
        "Retention policy: status / purge. Auto-purges traces, "
        "dead_letter, tool_calls, async_tasks, jobs older than the "
        "policy horizons. Operator-content tables (artifacts, "
        "knowledge_*, messages, cost_ledger) are NOT touched."
    ),
)
app.add_typer(schedule_app, name="schedule")
app.add_typer(traces_app, name="traces")
app.add_typer(heuristics_app, name="heuristics")
app.add_typer(dead_letter_app, name="dead-letter")
app.add_typer(async_tasks_app, name="async-tasks")
app.add_typer(retention_app, name="retention")

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
def artifacts(
    tag: str = typer.Option("", "--tag", help="Filter by tag substring"),
    limit: int = typer.Option(25, "--limit"),
    tainted_only: bool = typer.Option(
        False, "--tainted", help="Only rows with tainted=1",
    ),
) -> None:
    """List stored artifacts (metadata only — use `botctl artifact-show <id>`
    for content)."""
    from ..memory import artifacts as artifacts_mod
    conn = connect()
    try:
        rows = artifacts_mod.list_artifacts(conn, tag=tag or None, limit=limit)
    finally:
        conn.close()
    if tainted_only:
        rows = [r for r in rows if r.get("tainted")]

    t = Table("id", "name", "mime", "bytes", "tainted", "tags", "created")
    for r in rows:
        t.add_row(
            r["id"],
            (r.get("name") or "")[:40],
            r.get("mime", "") or "",
            str(r.get("bytes") or 0),
            "⚠️" if r.get("tainted") else "",
            (r.get("tags") or "")[:30],
            str(r.get("created_at") or "")[:19],
        )
    console.print(t)
    console.print(f"[dim]{len(rows)} shown[/dim]")


@app.command("artifact-show")
def artifact_show(
    artifact_id: str,
    offset: int = typer.Option(0, "--offset"),
    length: int = typer.Option(4000, "--length"),
) -> None:
    """Read the content of an artifact. Binary artifacts print metadata
    only — use `offset`/`length` to slice large text artifacts."""
    from ..memory import artifacts as artifacts_mod
    conn = connect()
    try:
        loaded = artifacts_mod.load_artifact_bytes(conn, artifact_id)
    finally:
        conn.close()
    if loaded is None:
        console.print(f"[red]artifact {artifact_id} not found[/red]")
        raise typer.Exit(1)
    data, meta = loaded
    console.print(
        f"[bold]{artifact_id}[/bold]  "
        f"name={meta.get('name')!r}  mime={meta.get('mime')}  "
        f"bytes={meta.get('bytes')}  "
        f"tainted={'yes' if meta.get('tainted') else 'no'}"
    )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        console.print("[yellow](binary; not printing)[/yellow]")
        return
    excerpt = text[offset: offset + length]
    console.print(excerpt)
    if len(text) > offset + length:
        console.print(
            f"[dim]… {len(text) - offset - length} more chars "
            f"(use --offset {offset + length} --length {length})[/dim]"
        )


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


@heuristics_app.command("list")
def heuristics_list(scope: str) -> None:
    """List all heuristics for a scope — proposed / active / retired."""
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


@heuristics_app.command("approve")
def heuristics_approve(heuristic_id: str) -> None:
    """Approve a proposed heuristic — flip status to `active`. The rule
    starts influencing every subsequent job in its scope immediately."""
    conn = connect()
    try:
        row = prompts_mod.get_heuristic(conn, heuristic_id=heuristic_id)
    finally:
        conn.close()
    if row is None:
        console.print(f"[red]heuristic {heuristic_id} not found[/red]")
        raise typer.Exit(1)
    if row["status"] == "active":
        console.print(f"[yellow]{heuristic_id} is already active[/yellow]")
        raise typer.Exit(0)
    if row["status"] == "retired":
        console.print(f"[yellow]{heuristic_id} was retired — "
                      f"approving will reactivate it[/yellow]")
    conn = connect()
    try:
        with transaction(conn):
            prompts_mod.approve_heuristic(conn, heuristic_id=heuristic_id)
    finally:
        conn.close()
    console.print(f"✅ approved [bold]{heuristic_id}[/bold]: {row['heuristic']}")


@heuristics_app.command("retire")
def heuristics_retire(heuristic_id: str) -> None:
    """Retire an active heuristic — flip status to `retired`. The rule stops
    influencing future jobs but the row stays for audit."""
    conn = connect()
    try:
        row = prompts_mod.get_heuristic(conn, heuristic_id=heuristic_id)
    finally:
        conn.close()
    if row is None:
        console.print(f"[red]heuristic {heuristic_id} not found[/red]")
        raise typer.Exit(1)
    if row["status"] == "retired":
        console.print(f"[yellow]{heuristic_id} is already retired[/yellow]")
        raise typer.Exit(0)
    conn = connect()
    try:
        with transaction(conn):
            prompts_mod.retire_heuristic(conn, heuristic_id=heuristic_id)
    finally:
        conn.close()
    console.print(f"🗑️  retired [bold]{heuristic_id}[/bold]: {row['heuristic']}")


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
def schedule_add(
    cron_expr: str,
    task: str,
    agent_scope: str = "orchestrator",
    target_channel: str = typer.Option(
        None,
        "--target-channel",
        help=(
            "Slack channel ID (C0...) to deliver the reply to when this "
            "schedule fires. If omitted the schedule still fires but its "
            "job has no thread_id, so the reply only appears in "
            "`botctl jobs`. Use `/schedule` from Slack for automatic "
            "destination capture via the channel-select modal field."
        ),
    ),
) -> None:
    """Add a cron schedule. CLI-created schedules with no
    `--target-channel` will fire successfully but their replies sit in
    `outbox_updates` undeliverable. The Slack-side `/schedule` slash
    command opens a modal that captures the channel automatically and
    is the recommended path.
    """
    from ..memory import threads as threads_mod
    conn = connect()
    try:
        with transaction(conn):
            thread_id: str | None = None
            if target_channel:
                thread_id = threads_mod.get_or_create_thread(
                    conn,
                    channel_id=target_channel,
                    thread_external_id=None,
                )
            sid = sched_mod.insert_schedule(
                conn, cron_expr=cron_expr, task=task,
                agent_scope=agent_scope, thread_id=thread_id,
                target_channel_id=target_channel,
            )
    finally:
        conn.close()
    suffix = (
        f" → channel `{target_channel}`"
        if target_channel
        else " (no destination — replies visible only via `botctl jobs`)"
    )
    console.print(f"📅 scheduled [bold]{sid}[/bold] — `{cron_expr}`{suffix}")


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


# ---- slack-doctor -----------------------------------------------------------
#
# Operator health check for Slack — every drift class in one command.
# Codex's 2026-05-01 review flagged Slack permission drift as a real
# silent-failure risk: scopes change, channel membership changes,
# tokens get revoked, and Donna goes quiet without an obvious symptom.
# slack-doctor surfaces every drift class in 5 seconds.
#
# Required scopes per the v0.5.0 manifest: chat:write, commands,
# app_mentions:read, im:history, im:write. Anything missing is a
# delivery-affecting bug that's worth flagging loud.


_SLACK_REQUIRED_SCOPES = (
    "chat:write",
    "commands",
    "app_mentions:read",
    "im:history",
    "im:write",
)


@app.command("slack-doctor")
def slack_doctor(
    delivery_channel: str = typer.Option(
        None,
        "--delivery-channel",
        help=(
            "Optional channel ID (C...) to probe with a one-line message. "
            "If omitted, delivery test is skipped."
        ),
    ),
) -> None:
    """Slack health check: token, scopes, Socket Mode, allowlist,
    optional delivery probe. Exit 0 = all green; exit 1 = at least
    one red flag."""
    from slack_sdk.errors import SlackApiError
    from slack_sdk.web.client import WebClient

    s = settings()
    bot_token = s.slack_bot_token or ""
    app_token = s.slack_app_token or ""
    team_id = s.slack_team_id or ""
    user_id = s.slack_allowed_user_id or ""

    failures: list[str] = []

    def _ok(msg: str) -> None:
        console.print(f"[green]OK[/green]  {msg}")

    def _warn(msg: str) -> None:
        console.print(f"[yellow]WARN[/yellow]  {msg}")
        # Warnings don't fail the command — caller decides if they care.

    def _fail(msg: str) -> None:
        console.print(f"[red]FAIL[/red]  {msg}")
        failures.append(msg)

    # 1. Config presence ---------------------------------------------------
    console.print("[bold]config[/bold]")
    if not bot_token.startswith("xoxb-"):
        _fail(f"SLACK_BOT_TOKEN missing or wrong shape (got {bot_token[:5]!r}…)")
    else:
        _ok(f"SLACK_BOT_TOKEN present ({bot_token[:8]}…)")
    if not app_token.startswith("xapp-"):
        _fail(f"SLACK_APP_TOKEN missing or wrong shape (got {app_token[:5]!r}…)")
    else:
        _ok(f"SLACK_APP_TOKEN present ({app_token[:8]}…)")
    if not team_id:
        _fail("SLACK_TEAM_ID empty")
    else:
        _ok(f"SLACK_TEAM_ID = {team_id}")
    if not user_id:
        _fail("SLACK_ALLOWED_USER_ID empty")
    else:
        _ok(f"SLACK_ALLOWED_USER_ID = {user_id}")
    if failures:
        console.print(f"\n[red]slack-doctor: {len(failures)} fail(s); cannot proceed[/red]")
        raise typer.Exit(1)

    client = WebClient(token=bot_token)

    # 2. Bot token + scopes ----------------------------------------------
    console.print("\n[bold]bot token[/bold]")
    try:
        auth = client.auth_test()
    except SlackApiError as e:
        code = (
            e.response.data.get("error")
            if hasattr(e, "response") and isinstance(e.response.data, dict)
            else "unknown"
        )
        _fail(f"auth.test rejected: {code}")
        console.print("\n[red]slack-doctor: token invalid; aborting[/red]")
        raise typer.Exit(1) from e
    _ok(f"auth.test ok — bot user {auth.get('user_id')} ({auth.get('user')})")
    if auth.get("team_id") != team_id:
        _fail(
            f"team_id from token ({auth.get('team_id')}) doesn't match "
            f"SLACK_ALLOWED_USER_ID's team ({team_id}). Token-vs-allowlist "
            f"mismatch silently drops every event."
        )
    else:
        _ok("token's team matches SLACK_TEAM_ID")

    scope_header = (
        auth.headers.get("x-oauth-scopes", "")
        if hasattr(auth, "headers") else ""
    )
    granted = {s.strip() for s in scope_header.split(",") if s.strip()}
    missing = [sc for sc in _SLACK_REQUIRED_SCOPES if sc not in granted]
    if missing:
        _fail(f"missing required scopes: {', '.join(missing)}")
    else:
        _ok(f"all required scopes present ({len(_SLACK_REQUIRED_SCOPES)})")
    extra = sorted(granted - set(_SLACK_REQUIRED_SCOPES))
    if extra:
        _warn(f"extra scopes granted (not required by v0.5.0): {', '.join(extra)}")

    # 3. App-level token (Socket Mode) -----------------------------------
    # slack_sdk requires app_token as a keyword arg to
    # apps_connections_open() *even when* the WebClient was constructed
    # with that token. Constructing with the token sets the default for
    # OTHER methods but apps.* methods enforce explicit pass-through
    # because they're scoped to the app rather than the bot.
    console.print("\n[bold]app-level token (Socket Mode)[/bold]")
    app_client = WebClient(token=app_token)
    try:
        opened = app_client.apps_connections_open(app_token=app_token)
        if opened.get("ok") and opened.get("url"):
            _ok("apps.connections.open succeeded — Socket Mode reachable")
        else:
            _fail(f"apps.connections.open returned non-ok: {opened.data}")
    except SlackApiError as e:
        code = (
            e.response.data.get("error")
            if hasattr(e, "response") and isinstance(e.response.data, dict)
            else "unknown"
        )
        _fail(f"apps.connections.open rejected: {code}")
    except Exception as e:  # noqa: BLE001
        # Catch TypeError from API drift (kwarg requirements changing)
        # and similar non-Slack-API failures so the doctor reports loud
        # but doesn't crash mid-check.
        _fail(f"apps.connections.open raised {type(e).__name__}: {e}")

    # 4. Channels Donna is in ---------------------------------------------
    # V60-4 (v0.6.2): users.conversations needs `channels:read` (and
    # `groups:read` for private). The v0.5.0 manifest deliberately omits
    # both per Codex's privacy review ("would let bot read all channel
    # chat, not just mentions. Privacy + token blast radius."). Channel
    # listing is operator situational awareness, NOT a runtime
    # requirement — the bot delivers via the channels it's been
    # explicitly invited to regardless. Demote `missing_scope` here to
    # WARN so slack-doctor exits 0 on a healthy-but-minimally-scoped
    # bot.
    console.print("\n[bold]bot channel membership[/bold]")
    try:
        chans = client.users_conversations(
            user=auth.get("user_id"),
            types="public_channel,private_channel,im",
            limit=200,
        )
        members = chans.get("channels", []) or []
        ims = [c for c in members if c.get("is_im")]
        public = [c for c in members if c.get("is_channel") and not c.get("is_private")]
        private = [c for c in members if c.get("is_private")]
        _ok(
            f"member of {len(members)} conversations "
            f"({len(public)} public, {len(private)} private, {len(ims)} DMs)"
        )
        for c in public + private:
            console.print(f"    - #{c.get('name')} ({c.get('id')})")
    except SlackApiError as e:
        code = (
            e.response.data.get("error")
            if hasattr(e, "response") and isinstance(e.response.data, dict)
            else "unknown"
        )
        if code == "missing_scope":
            _warn(
                "users.conversations: missing_scope (channels:read / "
                "groups:read deliberately not granted per v0.5.0 "
                "security review). Channel listing skipped; bot still "
                "delivers to invited channels normally."
            )
        else:
            _fail(f"users.conversations failed: {code}")

    # 5. Optional delivery probe ------------------------------------------
    if delivery_channel:
        console.print(f"\n[bold]delivery probe -> {delivery_channel}[/bold]")
        try:
            posted = client.chat_postMessage(
                channel=delivery_channel,
                text="🔍 slack-doctor probe — ignore",
                unfurl_links=False,
                unfurl_media=False,
            )
            ts = posted.get("ts")
            _ok(f"chat.postMessage delivered (ts={ts})")
            # Clean up the probe so the channel doesn't accrete noise.
            try:
                client.chat_delete(channel=delivery_channel, ts=ts)
                _ok("probe message deleted")
            except SlackApiError as e:
                _warn(f"probe sent but delete failed: {e.response.data.get('error', 'unknown')}")
        except SlackApiError as e:
            code = (
                e.response.data.get("error")
                if hasattr(e, "response") and isinstance(e.response.data, dict)
                else "unknown"
            )
            _fail(f"chat.postMessage rejected: {code}")

    # Summary -------------------------------------------------------------
    console.print()
    if failures:
        console.print(
            f"[red]slack-doctor: {len(failures)} red flag(s)[/red]"
        )
        for f in failures:
            console.print(f"  - {f}")
        raise typer.Exit(1)
    console.print("[green]slack-doctor: all green[/green]")


# ---- dead-letter ------------------------------------------------------------
#
# Operator UX for the v0.5.1 outbox_dead_letter table. Codex's 2026-05-01
# review: "smoke alarm without a panel = noise." When the V50-1 classifier
# routes a delivery failure to dead-letter, the operator gets a throttled
# DM AND can come here to inspect / retry / discard.


def _dl_age(moved_at: str | None) -> str:
    if not moved_at:
        return "?"
    try:
        dt = (
            datetime.fromisoformat(moved_at)
            if isinstance(moved_at, str) else moved_at
        )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - dt
        if delta.days >= 1:
            return f"{delta.days}d"
        h = delta.seconds // 3600
        if h:
            return f"{h}h"
        m = (delta.seconds % 3600) // 60
        return f"{m}m"
    except (TypeError, ValueError):
        return "?"


@dead_letter_app.command("list")
def dead_letter_list(
    since: str = typer.Option(
        "all", help="'30m' | '3h' | '1d' | '1w' | 'all'",
    ),
    error_class: str = typer.Option(
        None, "--class",
        help="Filter by error_class: terminal | unknown",
    ),
    limit: int = 50,
) -> None:
    """Show recent dead-lettered outbox rows."""
    delta = _parse_since(since)
    where: list[str] = []
    params: list = []
    if delta is not None:
        where.append("moved_at >= ?")
        params.append(datetime.now(UTC) - delta)
    if error_class:
        where.append("error_class = ?")
        params.append(error_class)
    sql = "SELECT id, source_table, source_id, job_id, channel_id, " \
          "error_code, error_class, attempt_count, moved_at " \
          "FROM outbox_dead_letter"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY moved_at DESC LIMIT ?"
    params.append(limit)
    conn = connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) c FROM outbox_dead_letter"
        ).fetchone()["c"]
    finally:
        conn.close()
    if not rows:
        console.print("[dim]no dead-letter rows match[/dim]")
        return
    table = Table(title=f"Dead-letter ({len(rows)} of {total})")
    table.add_column("dl id")
    table.add_column("kind")
    table.add_column("error")
    table.add_column("class")
    table.add_column("channel")
    table.add_column("attempts", justify="right")
    table.add_column("age")
    for r in rows:
        table.add_row(
            r["id"], r["source_table"], r["error_code"], r["error_class"],
            (r["channel_id"] or "")[:12], str(r["attempt_count"]),
            _dl_age(r["moved_at"]),
        )
    console.print(table)


@dead_letter_app.command("show")
def dead_letter_show(dl_id: str) -> None:
    """Full provenance + payload of one dead-letter row."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM outbox_dead_letter WHERE id = ?", (dl_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        console.print(f"[red]dead-letter {dl_id} not found[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{dl_id}[/bold]")
    for k in (
        "source_table", "source_id", "job_id", "channel_id", "thread_ts",
        "tainted", "error_code", "error_class", "attempt_count",
        "first_attempt_at", "last_attempt_at", "moved_at",
    ):
        console.print(f"  {k}: {row[k]}")
    payload = row["payload"] or ""
    if len(payload) > 2000:
        console.print(f"\n[dim]payload ({len(payload)} chars, first 2000):[/dim]")
        console.print(payload[:2000])
    else:
        console.print(f"\n[dim]payload:[/dim]\n{payload}")


@dead_letter_app.command("retry")
def dead_letter_retry(
    dl_id: str,
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation",
    ),
) -> None:
    """Move a dead-letter row back to its source outbox table for one
    more delivery attempt. Use after fixing the underlying issue
    (re-invite Donna to the channel, restore archived channel, etc.).

    Resets attempt_count on the source row so it gets a fresh count
    against the v0.5.1 classifier's max-retries policy.
    """
    import uuid

    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM outbox_dead_letter WHERE id = ?", (dl_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        console.print(f"[red]dead-letter {dl_id} not found[/red]")
        raise typer.Exit(1)

    if row["source_table"] != "outbox_updates":
        # We currently only dead-letter from outbox_updates (v0.5.1).
        # Future kinds would need their own retry path.
        console.print(
            f"[red]retry not supported for source_table="
            f"{row['source_table']!r}[/red]"
        )
        raise typer.Exit(2)

    console.print(f"[bold]{dl_id}[/bold]  -> outbox_updates")
    console.print(f"  channel: {row['channel_id']}")
    console.print(f"  job: {row['job_id']}")
    console.print(f"  error: {row['error_code']} ({row['error_class']})")
    console.print(f"  prior attempts: {row['attempt_count']}")

    if not force:
        confirmed = typer.confirm(
            "Re-enqueue this row for delivery?", default=False,
        )
        if not confirmed:
            console.print("[dim]aborted[/dim]")
            raise typer.Exit(0)

    new_id = f"upd_{uuid.uuid4().hex[:12]}"
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "INSERT INTO outbox_updates "
                "(id, job_id, text, tainted) "
                "VALUES (?, ?, ?, ?)",
                (
                    new_id, row["job_id"], row["payload"] or "",
                    int(row["tainted"]),
                ),
            )
            conn.execute(
                "DELETE FROM outbox_dead_letter WHERE id = ?", (dl_id,),
            )
    finally:
        conn.close()
    console.print(f"♻️  re-enqueued as {new_id}")


@dead_letter_app.command("discard")
def dead_letter_discard(
    dl_id: str,
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip confirmation",
    ),
) -> None:
    """Permanently delete a dead-letter row. No retry, no recovery."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id, channel_id, error_code, attempt_count "
            "FROM outbox_dead_letter WHERE id = ?",
            (dl_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        console.print(f"[red]dead-letter {dl_id} not found[/red]")
        raise typer.Exit(1)
    console.print(
        f"[bold]{dl_id}[/bold]  channel={row['channel_id']}  "
        f"error={row['error_code']}  attempts={row['attempt_count']}"
    )
    if not force:
        confirmed = typer.confirm(
            "Permanently discard?", default=False,
        )
        if not confirmed:
            console.print("[dim]aborted[/dim]")
            raise typer.Exit(0)
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "DELETE FROM outbox_dead_letter WHERE id = ?", (dl_id,),
            )
    finally:
        conn.close()
    console.print(f"🗑️  discarded {dl_id}")


# ---- async-tasks ------------------------------------------------------------
#
# Operator UX for the v0.6 supervised work queue. Mirrors dead-letter shape
# but read-only (retry happens automatically per AsyncTaskRunner policy).


@async_tasks_app.command("list")
def async_tasks_list(
    status: str = typer.Option(
        None, "--status",
        help="Filter: pending | running | done | failed",
    ),
    kind: str = typer.Option(None, "--kind"),
    limit: int = 50,
) -> None:
    """Show recent async_tasks rows."""
    from ..memory import async_tasks as at_mod
    conn = connect()
    try:
        rows = at_mod.list_tasks(
            conn, status=status, kind=kind, limit=limit,
        )
        counts = at_mod.count_by_status(conn)
    finally:
        conn.close()
    summary = " · ".join(
        f"{k}={v}" for k, v in sorted(counts.items())
    ) or "empty"
    if not rows:
        console.print(f"[dim]no rows match · totals: {summary}[/dim]")
        return
    table = Table(title=f"async_tasks · totals: {summary}")
    table.add_column("id")
    table.add_column("kind")
    table.add_column("status")
    table.add_column("attempts", justify="right")
    table.add_column("scheduled_for")
    table.add_column("last_error")
    for r in rows:
        err = (r["last_error"] or "")[:60]
        table.add_row(
            r["id"], r["kind"], r["status"], str(r["attempts"]),
            str(r["scheduled_for"])[:19], err,
        )
    console.print(table)


@async_tasks_app.command("show")
def async_tasks_show(task_id: str) -> None:
    """Full row for one async_tasks entry."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM async_tasks WHERE id = ?", (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        console.print(f"[red]async_task {task_id} not found[/red]")
        raise typer.Exit(1)
    console.print(f"[bold]{task_id}[/bold]")
    for k in (
        "kind", "status", "attempts", "scheduled_for",
        "created_at", "started_at", "finished_at",
        "locked_by", "locked_until", "last_error",
    ):
        console.print(f"  {k}: {row[k]}")
    payload = row["payload"] or ""
    if len(payload) > 2000:
        console.print(f"\n[dim]payload ({len(payload)} chars, first 2000):[/dim]")
        console.print(payload[:2000])
    else:
        console.print(f"\n[dim]payload:[/dim]\n{payload}")


# ---- retention --------------------------------------------------------------


@retention_app.command("status")
def retention_status() -> None:
    """Show per-table row totals and counts that auto-purge would
    delete. Read-only; safe to run anytime."""
    from ..memory import retention as ret_mod

    conn = connect()
    try:
        report = ret_mod.status(conn)
    finally:
        conn.close()
    table = Table("table", "total", "would purge", "policy (days)")
    for name, info in report.items():
        policy_days = ret_mod.RETENTION_DAYS.get(
            name,
            ret_mod.RETENTION_DAYS.get(f"{name}_terminal", "n/a"),
        )
        table.add_row(
            name,
            str(info.get("total", 0)),
            str(info.get("would_purge", 0)),
            str(policy_days),
        )
    console.print(table)


@retention_app.command("purge")
def retention_purge(
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show counts without deleting (alias of `retention status`).",
    ),
) -> None:
    """Apply retention policy: delete rows older than each table's
    horizon. Idempotent — safe to run repeatedly."""
    from ..memory import retention as ret_mod

    conn = connect()
    try:
        with transaction(conn):
            counts = ret_mod.purge_old(conn, dry_run=dry_run)
    finally:
        conn.close()
    verb = "would purge" if dry_run else "purged"
    table = Table("table", verb)
    for name, n in counts.items():
        table.add_row(name, str(n))
    console.print(table)
    total = sum(counts.values())
    console.print(f"[dim]total rows {verb}: {total}[/dim]")


if __name__ == "__main__":
    app()
