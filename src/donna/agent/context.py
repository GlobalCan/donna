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
from ..memory import jobs as jobs_mod
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
        except LeaseLost:
            log.error("agent.job.lease_lost_aborted", job_id=job_id, worker_id=worker_id)
        finally:
            ctx.stop_hb.set()
            if ctx.hb_task:
                try:
                    await asyncio.wait_for(ctx.hb_task, timeout=2.0)
                except TimeoutError:
                    ctx.hb_task.cancel()

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
            return _err_block(tu["id"], f"tool {name} not registered")
        if "*" not in entry.agents and scope not in entry.agents:
            return _err_block(tu["id"], f"tool {name} not allowed for scope {scope}")

        consent_res = await consent_mod.check(
            job_id=self.job.id, entry=entry, arguments=args, tainted=self.state.tainted,
        )
        if not consent_res.approved:
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
        """Owner-guarded final write + DONE transition."""
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
                return jobs_mod.set_status(
                    conn, self.state.job_id, JobStatus.DONE, worker_id=self.worker_id,
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
