"""JobContext — shared primitives that ALL modes (chat, grounded, speculative,
debate) must use. Fixes Codex's #2 + #15: no more two-headed execution split.

Primitives:
 - load state (resume-aware, cost-authoritative from ledger)
 - heartbeat (continuous 30s background task for owner-guarded writes)
 - compose (mode-aware system prompt)
 - model step (rate-limited, traced, cost-recorded)
 - tool step (parallel, pre-tainted, consent-gated, checkpointed)
 - consent wait (DB-persisted pending state; survives restart)
 - compact (every N tool calls)
 - checkpoint (owner-guarded; raises LeaseLost on failure)
 - finalize (owner-guarded DONE transition)

Every mode is a graph variant that calls these in a different order.
"""
from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Any

from ..config import settings
from ..logging import get_logger
from ..memory import brief_runs as brief_runs_mod
from ..memory import jobs as jobs_mod
from ..memory import outbox as outbox_mod
from ..memory import tool_calls as tool_calls_mod
from ..memory.db import connect, transaction
from ..observability import otel
from ..security import consent as consent_mod
from ..tools.registry import REGISTRY
from ..types import JobState, JobStatus, ModelTier
from .model_adapter import GenerateResult, model

log = get_logger(__name__)


class LeaseLost(Exception):
    """Worker attempted a guarded write and found it has lost ownership."""


class JobCancelled(Exception):
    """User flipped the job to CANCELLED via /cancel or botctl.
    Mode handlers catch this between steps to tear down cleanly without
    finalizing to DONE."""


class JobContext:
    """Shared primitives for a single job's execution.

    Usage pattern (any mode):

        async with JobContext.open(job_id, worker_id) as ctx:
            # ... call ctx.retrieve / ctx.model_step / ctx.tool_step /
            #     ctx.checkpoint / ctx.compact as needed for this mode
            ctx.state.final_text = ...
            ctx.state.done = True
            # context manager finalizes + owner-guards the DONE transition
    """

    def __init__(self, job, worker_id: str):
        self.job = job
        self.worker_id = worker_id
        self.state: JobState = _init_state(job)
        self.stop_hb = asyncio.Event()
        self.hb_task: asyncio.Task | None = None
        # V50-8 (v0.5.2): when finalize() inserts a tainted assistant
        # message, it stashes the row id + raw content here so the
        # post-finalize hook in `open()` can spawn an async sanitizer
        # backfill task. Both fields stay None for clean jobs.
        self.assistant_message_id: str | None = None
        self.assistant_content: str | None = None

    @classmethod
    @asynccontextmanager
    async def open(cls, job_id: str, worker_id: str):
        job = _load_job_or_none(job_id)
        if job is None:
            log.error("agent.loop.missing_job", job_id=job_id)
            return
        ctx = cls(job, worker_id)
        ctx.hb_task = asyncio.create_task(
            _heartbeat_loop(job_id, worker_id, ctx.stop_hb)
        )
        try:
            with otel.span(
                "agent.job",
                **{
                    "agent.job.id": job_id,
                    "agent.scope": job.agent_scope,
                    "agent.mode": job.mode.value,
                    "agent.job.task_preview": job.task[:200],
                },
            ):
                yield ctx
                # Auto-finalize if the mode set done=True
                if ctx.state.done and not ctx.finalize():
                    raise LeaseLost(job_id)
                # V50-8 (v0.5.2): tainted assistant rows get an async
                # safe_summary backfill so the next chat job's prompt sees
                # a sanitized paraphrase (rendered unwrapped) instead of
                # the raw content (rendered wrapped).
                # v0.6 #2 (2026-05-02): enqueue to the durable async_tasks
                # queue instead of asyncio.create_task. Pre-fix the task
                # was lost on worker restart between finalize and Haiku
                # completion; now it survives via DB persistence with
                # retry/lease/dead-letter semantics.
                if (
                    ctx.state.done
                    and ctx.state.tainted
                    and ctx.assistant_message_id
                    and ctx.assistant_content
                ):
                    _enqueue_safe_summary_backfill(
                        message_id=ctx.assistant_message_id,
                        content=ctx.assistant_content,
                        job_id=ctx.job.id,
                    )
        except LeaseLost:
            log.error("agent.job.lease_lost_aborted", job_id=job_id, worker_id=worker_id)
        except JobCancelled:
            # User flipped status to CANCELLED via /cancel. Don't try to
            # finalize to DONE — the cancel path already set the terminal
            # state. Just checkpoint the partial state and exit cleanly.
            log.info("agent.job.cancelled", job_id=job_id, worker_id=worker_id)
            try:
                ctx.checkpoint()
            except Exception as e:  # noqa: BLE001
                log.warning("agent.job.cancelled_checkpoint_failed",
                            job_id=job_id, error=str(e))
        finally:
            ctx.stop_hb.set()
            if ctx.hb_task:
                try:
                    await asyncio.wait_for(ctx.hb_task, timeout=2.0)
                except TimeoutError:
                    ctx.hb_task.cancel()

    # -- cancellation check ---------------------------------------------------
    def check_cancelled(self) -> None:
        """Raise JobCancelled if the user flipped this job to CANCELLED.
        Modes should call this between model_step / tool_step iterations so
        /cancel is effective mid-run, not just between end_turns."""
        conn = connect()
        try:
            row = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (self.job.id,),
            ).fetchone()
        finally:
            conn.close()
        if row and row["status"] == JobStatus.CANCELLED.value:
            raise JobCancelled(self.job.id)

    # -- model step -----------------------------------------------------------
    async def model_step(
        self,
        *,
        system_blocks: list[dict[str, Any]],
        messages: list[dict[str, Any]] | None = None,
        tier: ModelTier = ModelTier.STRONG,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
    ) -> GenerateResult:
        msgs = messages if messages is not None else self.state.messages
        with otel.span("agent.turn"):
            result = await model().generate(
                system=system_blocks,
                messages=msgs,
                tools=tools,
                tier=tier,
                job_id=self.job.id,
                max_tokens=max_tokens,
            )
        self.state.cost_usd += result.cost_usd
        return result

    # -- tool step ------------------------------------------------------------
    async def tool_step(self, tool_uses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute parallel tool calls with pre-taint + consent + checkpoint.
        Returns the tool_result blocks to append to messages."""
        already_done = _already_executed_tool_use_ids(self.state)
        fresh = [tu for tu in tool_uses if tu.get("id") not in already_done]
        if len(fresh) != len(tool_uses):
            log.info("agent.resume.dedup", job_id=self.job.id,
                     skipped=len(tool_uses) - len(fresh))

        # Pre-scan: taint the job if any fresh tool is taint-marking
        for tu in fresh:
            e = REGISTRY.get(tu.get("name", ""))
            if e is not None and e.taints_job and not self.state.tainted:
                self.state.tainted = True
                self.state.taint_source_tool = f"batch:{e.name}"
                otel.set_attr("agent.job.tainted", True)
                otel.set_attr("agent.taint.source_tool", self.state.taint_source_tool)
                break

        fresh_results = await asyncio.gather(*[
            self._execute_one(tu) for tu in fresh
        ])

        # Rebuild full ordered list, synthesizing replayed markers for skipped
        full: list[dict[str, Any]] = []
        fresh_iter = iter(fresh_results)
        for tu in tool_uses:
            if tu.get("id") in already_done:
                full.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": json.dumps({"replayed": True}),
                    "is_error": False,
                })
            else:
                full.append(next(fresh_iter))

        self.state.tool_calls_count += len(tool_uses)
        return full

    async def _execute_one(self, tu: dict[str, Any]) -> dict[str, Any]:
        name = tu["name"]
        args = tu.get("input", {}) or {}
        scope = self.job.agent_scope
        entry = REGISTRY.get(name)
        if entry is None:
            # Audit the attempted bypass (Codex GPT-5.3-codex finding RF5):
            # the model tried to call a tool that doesn't exist. Operators
            # need this in `tool_calls` so `botctl traces` and the watchdog
            # can see adversarial probing. Pre-fix this returned an error
            # to the model and wrote nothing to the audit table.
            self._audit_rejection(name, args, "unknown_tool",
                                  f"tool {name} not registered")
            return _err_block(tu["id"], f"tool {name} not registered")
        if "*" not in entry.agents and scope not in entry.agents:
            self._audit_rejection(name, args, "not_allowlisted",
                                  f"tool {name} not allowed for scope {scope}")
            return _err_block(tu["id"], f"tool {name} not allowed for scope {scope}")

        consent_res = await consent_mod.check(
            job_id=self.job.id, entry=entry, arguments=args,
            tainted=self.state.tainted, worker_id=self.worker_id,
        )
        if not consent_res.approved:
            # "lease_lost" means we're a stale worker (Codex #8). The next
            # guarded checkpoint will raise LeaseLost so JobContext.open
            # unwinds cleanly; in the meantime, return an error tool_result.
            self._audit_rejection(name, args, f"denied:{consent_res.reason}",
                                  f"user declined ({consent_res.reason})")
            return _err_block(tu["id"], f"user declined ({consent_res.reason})")

        import inspect
        sig = inspect.signature(entry.fn)
        if "job_id" in sig.parameters and "job_id" not in args:
            args["job_id"] = self.job.id
        if "agent_scope" in sig.parameters and "agent_scope" not in args and scope != "orchestrator":
            args["agent_scope"] = scope
        if "tainted" in sig.parameters and "tainted" not in args:
            args["tainted"] = self.state.tainted

        t0 = time.perf_counter()
        with otel.span(
            f"agent.tool.{name}",
            **{
                "agent.tool.name": name,
                "agent.tool.scope": entry.scope,
                "agent.tool.cost": entry.cost,
                "agent.job.id": self.job.id,
            },
        ):
            try:
                result = await entry.fn(**args)
                status = "done"
                error = None
            except Exception as e:
                log.exception("agent.tool.error", tool=name, error=str(e))
                result = {"error": str(e)}
                status = "error"
                error = str(e)
        duration_ms = int((time.perf_counter() - t0) * 1000)

        # Post-exec taint propagation from tool result metadata
        if isinstance(result, dict) and result.get("tainted") and not self.state.tainted:
            self.state.tainted = True
            self.state.taint_source_tool = name
            otel.set_attr("agent.job.tainted", True)
            otel.set_attr("agent.taint.source_tool", name)

        conn = connect()
        try:
            tool_calls_mod.insert_tool_call(
                conn, job_id=self.job.id, tool_name=name, arguments=args,
                result=result if isinstance(result, (dict, list, str)) else str(result),
                duration_ms=duration_ms, idempotent=entry.idempotent,
                tainted=self.state.tainted, status=status, error=error,
            )
        finally:
            conn.close()

        if isinstance(result, dict) and "artifact_id" in result:
            self.state.artifact_refs.append(str(result["artifact_id"]))

        return {
            "type": "tool_result",
            "tool_use_id": tu["id"],
            "content": json.dumps(result, default=str) if not isinstance(result, str) else result,
            "is_error": status == "error",
        }

    def _audit_rejection(
        self, tool_name: str, arguments: dict[str, Any],
        status: str, reason: str,
    ) -> None:
        """Persist a rejected tool-call attempt into `tool_calls` so
        operators can audit attempted bypasses via `botctl traces` and
        the watchdog. Used for unknown-tool, not-allowlisted, and
        consent-denied paths in `_execute_one` (Codex GPT-5.3-codex
        RF5 — net-new finding from cross-vendor review).

        Status values:
          - "unknown_tool"      — model called a tool that isn't registered
          - "not_allowlisted"   — tool exists but isn't in this scope's set
          - "denied:<reason>"   — consent gate rejected (timeout / "no" / lease_lost)

        Best-effort: a logging failure here must not break the agent
        loop. Swallow exceptions and log them.
        """
        try:
            conn = connect()
            try:
                tool_calls_mod.insert_tool_call(
                    conn,
                    job_id=self.job.id,
                    tool_name=tool_name,
                    arguments=arguments,
                    result={"rejected": True, "reason": reason},
                    duration_ms=0,
                    idempotent=True,
                    tainted=self.state.tainted,
                    status=status,
                    error=reason,
                )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            log.exception(
                "agent.tool.audit_failed",
                tool=tool_name, status=status, error=str(e),
            )

    # -- compaction -----------------------------------------------------------
    async def maybe_compact(self) -> None:
        n = settings().compact_every_n
        if self.state.tool_calls_count > 0 and self.state.tool_calls_count % n == 0:
            from .compaction import compact_messages
            self.state.messages = await compact_messages(
                self.state.messages,
                self.state.artifact_refs,
                job_id=self.state.job_id,
            )

    # -- checkpoint / finalize -----------------------------------------------
    def checkpoint(self) -> bool:
        """Owner-guarded save. Returns False if lease was lost."""
        conn = connect()
        try:
            with transaction(conn):
                return jobs_mod.save_checkpoint(
                    conn, self.state.job_id,
                    state=self.state.to_dict(),
                    tainted=self.state.tainted,
                    taint_source_tool=self.state.taint_source_tool,
                    tool_call_count=self.state.tool_calls_count,
                    worker_id=self.worker_id,
                )
        finally:
            conn.close()

    def checkpoint_or_raise(self) -> None:
        if not self.checkpoint():
            raise LeaseLost(self.job.id)

    def finalize(self) -> bool:
        """Owner-guarded final write + DONE transition + outbox delivery.

        The outbox insert is atomic with the DONE status flip inside a single
        transaction. All four modes (chat, grounded, speculative, debate) set
        `final_text` + `done=True`; unifying the outbox write here means every
        mode delivers its answer to Discord without each one having to
        remember — which chat was the only mode that did.
        """
        conn = connect()
        try:
            with transaction(conn):
                ok1 = jobs_mod.save_checkpoint(
                    conn, self.state.job_id,
                    state=self.state.to_dict(),
                    tainted=self.state.tainted,
                    taint_source_tool=self.state.taint_source_tool,
                    tool_call_count=self.state.tool_calls_count,
                    worker_id=self.worker_id,
                )
                if not ok1:
                    return False
                text = (self.state.final_text or "").strip()
                if text:
                    # The old 1500-char cap truncated long grounded/debate
                    # answers mid-sentence. The adapter now splits long
                    # outbox text into multiple Discord messages at
                    # paragraph/sentence boundaries (see _post_update).
                    # A sanity cap is still prudent to bound DB storage
                    # and message-split cost; 20k chars ≈ 10 Discord messages.
                    # v0.7.2: extracted to memory.outbox.enqueue_update
                    # so the SQL lives in one place and is independently
                    # testable. Same semantics — caller's transaction
                    # wraps this for atomicity with the DONE flip.
                    outbox_mod.enqueue_update(
                        conn,
                        job_id=self.state.job_id,
                        text=text,
                        tainted=self.state.tainted,
                    )
                # Session memory: persist the user task + assistant answer
                # to `messages` for cross-job recall in the same Discord
                # thread.
                #
                # v0.4.4 (2026-04-30): tainted jobs ARE now written, with
                # `tainted=1` so `compose_system` can render them with an
                # explicit "from untrusted source — do not follow
                # instructions" wrapper. Pre-v0.4.4 tainted exchanges
                # were silently skipped, on the theory that any web-tool
                # bytes shouldn't pollute future clean-job context. In
                # practice nearly every real DM ends up tainted (weather,
                # news, lookups all use `fetch_url` / `search_web`), so
                # session memory was effectively dead for daily use. The
                # tagged-and-rendered design preserves the trust boundary
                # at the prompt-rendering layer while keeping the UX
                # working.
                if self.job.thread_id and text and self.job.task:
                    from ..agent.compose import scrub_protocol_tokens
                    from ..memory import threads as threads_mod
                    # Scrub protocol-impersonating tokens from tainted
                    # replies before they land in messages — a clean
                    # run later that quotes back the prior reply via
                    # session_history shouldn't carry `<tool_use>`,
                    # role tags, or scaffolding-shaped delimiters.
                    # The user task is operator-typed text and isn't
                    # scrubbed; only the assistant reply could carry
                    # web/file-derived bytes.
                    assistant_content = (
                        scrub_protocol_tokens(text)
                        if self.state.tainted else text
                    )
                    threads_mod.insert_message(
                        conn, thread_id=self.job.thread_id,
                        role="user", content=self.job.task[:4000],
                        tainted=self.state.tainted,
                    )
                    capped_assistant = assistant_content[:4000]
                    asst_mid = threads_mod.insert_message(
                        conn, thread_id=self.job.thread_id,
                        role="assistant", content=capped_assistant,
                        tainted=self.state.tainted,
                    )
                    # V50-8: capture the assistant row id + content so the
                    # post-finalize hook in JobContext.open can fire the
                    # async safe_summary backfill task. Only matters for
                    # tainted rows; clean rows render as User/You dialogue
                    # directly from `content`.
                    if self.state.tainted:
                        self.assistant_message_id = asst_mid
                        self.assistant_content = capped_assistant
                ok = jobs_mod.set_status(
                    conn, self.state.job_id, JobStatus.DONE, worker_id=self.worker_id,
                )
                if ok and self.job.schedule_id:
                    # V70-1 (v0.7.3): keep brief_runs.status in sync with
                    # the underlying job. Most jobs aren't brief jobs and
                    # don't have a brief_runs row — the UPDATE matches 0
                    # rows for them, which is the intended is-this-a-brief
                    # filter. Inside the same transaction so a finalize
                    # rollback also rolls back the brief_runs flip; Codex's
                    # pitfall is "don't let services open their own
                    # transaction during finalize" — we don't.
                    brief_runs_mod.update_status_by_job_id(
                        conn,
                        job_id=self.state.job_id,
                        status="done",
                    )
                return ok
        finally:
            conn.close()


# ---------- V50-8 safe_summary backfill (v0.6 #2: queue-backed) -----------


def _enqueue_safe_summary_backfill(
    *, message_id: str, content: str, job_id: str,
) -> None:
    """Persist a safe_summary backfill request as an async_tasks row.

    Replaces v0.5.2's `asyncio.create_task(_backfill_safe_summary(...))`.
    Survives worker restart, has lease/retry/dead-letter semantics, and
    is observable via `botctl async-tasks list`. Worker's AsyncTaskRunner
    picks it up and dispatches to `handle_safe_summary_backfill` below.
    """
    from ..memory import async_tasks as at_mod
    from ..memory.db import connect, transaction

    try:
        conn = connect()
        try:
            with transaction(conn):
                at_mod.enqueue(
                    conn,
                    kind="safe_summary_backfill",
                    payload={
                        "message_id": message_id,
                        "content": content,
                        "job_id": job_id,
                    },
                )
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        # Enqueue failure is non-fatal: compose_system falls back to
        # wrapped-raw render on safe_summary IS NULL. Log so operators
        # can spot DB pressure.
        log.warning(
            "safe_summary.enqueue_failed",
            message_id=message_id, job_id=job_id, error=str(e),
        )


async def handle_safe_summary_backfill(payload: dict) -> None:
    """AsyncTaskRunner handler for kind='safe_summary_backfill'.

    Receives `{message_id, content, job_id}` from the queue. Calls the
    Haiku sanitizer, then UPDATEs `messages.safe_summary` if non-empty.
    Idempotent via `update_safe_summary`'s `WHERE safe_summary IS NULL`
    guard — re-runs after retry don't clobber a successful prior write.

    Raise on transient failure to trigger queue retry; suppress + log
    on terminal failure (e.g. message no longer exists).
    """
    from ..memory import threads as threads_mod
    from ..memory.db import connect, transaction
    from ..security.sanitize import sanitize_untrusted

    message_id = payload["message_id"]
    content = payload["content"]
    job_id = payload.get("job_id")

    summary = await sanitize_untrusted(
        content,
        artifact_id=f"msg:{message_id}",
        source_url=None,
        job_id=job_id,
    )
    if not summary or not summary.strip():
        log.info(
            "safe_summary.empty_summary_skipped",
            message_id=message_id, job_id=job_id,
        )
        return

    conn = connect()
    try:
        with transaction(conn):
            wrote = threads_mod.update_safe_summary(
                conn, message_id=message_id, summary=summary,
            )
        if wrote:
            log.debug(
                "safe_summary.persisted",
                message_id=message_id, job_id=job_id,
                summary_chars=len(summary),
            )
    finally:
        conn.close()


# ---------- helpers --------------------------------------------------------


def _load_job_or_none(job_id: str):
    conn = connect()
    try:
        return jobs_mod.get_job(conn, job_id)
    finally:
        conn.close()


def _init_state(job) -> JobState:
    if job.checkpoint_state:
        state = JobState.from_dict(job.checkpoint_state)
        # Resume authoritative cost from DB, not stale in-memory
        state.cost_usd = job.cost_usd
    else:
        state = JobState(
            job_id=job.id, agent_scope=job.agent_scope, mode=job.mode,
            tainted=job.tainted,
        )
        state.messages = [{"role": "user", "content": job.task}]
    return state


async def _heartbeat_loop(job_id: str, worker_id: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=30.0)
            return
        except TimeoutError:
            pass
        conn = connect()
        try:
            ok = jobs_mod.renew_lease(conn, job_id, worker_id)
        finally:
            conn.close()
        if not ok:
            log.warning("agent.heartbeat.lease_lost", job_id=job_id, worker_id=worker_id)
            stop.set()
            return


def _already_executed_tool_use_ids(state: JobState) -> set[str]:
    result_ids: set[str] = set()
    for msg in state.messages:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id")
                    if tid:
                        result_ids.add(tid)
    return result_ids


def _err_block(tool_use_id: str, msg: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps({"error": msg}),
        "is_error": True,
    }
