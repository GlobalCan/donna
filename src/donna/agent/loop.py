"""The agent loop — the ~120-line core.

Flow (per iteration):
  1. Check budget & rate (rate limiter internal to model adapter)
  2. Compose system prompt (cached prefix + volatile suffix)
  3. Compact if we've crossed N tool calls
  4. Call the model with tools
  5. If model returns text-only → done
  6. Else execute each tool call (parallel when independent)
  7. Append results, save checkpoint, repeat
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from ..config import settings
from ..logging import get_logger
from ..memory import jobs as jobs_mod
from ..memory import tool_calls as tool_calls_mod
from ..memory.db import connect, transaction
from ..observability import otel
from ..security import consent as consent_mod
from ..tools.registry import REGISTRY, anthropic_tool_defs
from ..types import JobMode, JobState, JobStatus, ModelTier
from .compose import compose_system
from .model_adapter import model

log = get_logger(__name__)


class LeaseLost(Exception):
    """Raised when a worker attempts a guarded write and finds it has lost
    ownership of the job (another worker reclaimed it). The loop aborts
    immediately rather than corrupting state."""


async def _heartbeat_loop(job_id: str, worker_id: str, stop: asyncio.Event) -> None:
    """Background task that renews the lease every ~30s for the duration of
    the job. Runs continuously including during long model calls and consent
    waits — closes the C2 lease-expiry-reclaim window."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=30.0)
            return
        except asyncio.TimeoutError:
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


async def run_job(
    job_id: str,
    worker_id: str,
    *,
    renewer: "JobRenewer",
) -> None:
    """Run one job to completion (or checkpoint + bail on non-fatal error)."""
    conn = connect()
    try:
        job = jobs_mod.get_job(conn, job_id)
    finally:
        conn.close()
    if job is None:
        log.error("agent.loop.missing_job", job_id=job_id)
        return

    # Load state (resume if checkpoint exists)
    if job.checkpoint_state:
        state = JobState.from_dict(job.checkpoint_state)
        # Resume cost from persisted authoritative value
        state.cost_usd = job.cost_usd
    else:
        state = JobState(
            job_id=job_id, agent_scope=job.agent_scope, mode=job.mode,
            tainted=job.tainted,
        )
        state.messages = [{"role": "user", "content": job.task}]

    # Spawn continuous heartbeat so lease doesn't expire during long awaits
    stop_hb = asyncio.Event()
    hb_task = asyncio.create_task(_heartbeat_loop(job_id, worker_id, stop_hb))

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
            # H1: Mode dispatch — grounded / speculative / debate have their
            # own handlers; only chat mode flows through the generic tool loop.
            if state.mode == JobMode.GROUNDED:
                await _run_mode_dispatch(
                    job_id, worker_id, job.agent_scope, job.task, state, mode="grounded"
                )
            elif state.mode == JobMode.SPECULATIVE:
                await _run_mode_dispatch(
                    job_id, worker_id, job.agent_scope, job.task, state, mode="speculative"
                )
            elif state.mode == JobMode.DEBATE:
                await _run_mode_dispatch(
                    job_id, worker_id, job.agent_scope, job.task, state, mode="debate"
                )
            else:
                await _loop(job_id, worker_id, job.agent_scope, job.task, state, renewer=renewer)
    except LeaseLost:
        log.error("agent.job.lease_lost_aborted", job_id=job_id, worker_id=worker_id)
        # Do NOT write checkpoint or final status — another worker owns this job now
        return
    finally:
        stop_hb.set()
        try:
            await asyncio.wait_for(hb_task, timeout=2.0)
        except asyncio.TimeoutError:
            hb_task.cancel()


async def _run_mode_dispatch(
    job_id: str, worker_id: str, scope: str, task: str, state: JobState, *, mode: str,
) -> None:
    """Handle grounded / speculative / debate single-shot modes."""
    if mode == "grounded":
        from ..modes.grounded import answer_grounded
        result = await answer_grounded(scope, task, job_id=job_id)
        state.final_text = _format_mode_reply("grounded", result)
    elif mode == "speculative":
        from ..modes.speculative import answer_speculative
        result = await answer_speculative(scope, task, job_id=job_id)
        state.final_text = _format_mode_reply("speculative", result)
    elif mode == "debate":
        from ..modes.debate import run_debate
        payload = json.loads(task) if task.startswith("{") else {"topic": task, "scope_a": scope, "scope_b": "orchestrator"}
        result = await run_debate(
            topic=payload.get("topic", task),
            scopes=[payload.get("scope_a", "orchestrator"), payload.get("scope_b", "orchestrator")],
            rounds=int(payload.get("rounds", 3)),
            job_id=job_id,
        )
        state.final_text = _format_mode_reply("debate", result)
    state.done = True
    _save_checkpoint_sync(state, worker_id=worker_id)
    _finish_job(job_id, state, worker_id=worker_id)


def _format_mode_reply(mode: str, result: dict[str, Any]) -> str:
    if result.get("refused"):
        return f"[{mode} · refused] {result.get('reason', 'no reason given')}"
    if mode == "grounded":
        return result.get("raw", "") + (
            f"\n\n_validated: {result.get('validated')}_" if "validated" in result else ""
        )
    if mode == "speculative":
        return (result.get("label", "🔮 SPECULATIVE") + "\n\n" + result.get("text", ""))
    if mode == "debate":
        summary = result.get("summary", "")
        transcript = result.get("transcript", [])
        lines = [f"**Debate: {' vs '.join(result.get('scopes', []))} on {result.get('topic','')}**\n"]
        for t in transcript:
            lines.append(f"\n### {t['scope']} — round {t['round']}\n{t['content']}")
        lines.append(f"\n---\n**Summary:**\n{summary}")
        return "\n".join(lines)
    return str(result)


async def _loop(
    job_id: str,
    worker_id: str,
    scope: str,
    task: str,
    state: JobState,
    *,
    renewer: "JobRenewer",
) -> None:
    s = settings()
    max_tool_calls = s.max_tool_calls_per_job
    compact_every = s.compact_every_n

    # H2: resume dedup — collect tool_use_ids already executed in prior crash
    already_executed_ids = _already_executed_tool_use_ids(state)

    while not state.done and state.tool_calls_count < max_tool_calls:
        # Propagate taint attrs onto the current span
        otel.set_attr("agent.job.tainted", state.tainted)
        if state.taint_source_tool:
            otel.set_attr("agent.taint.source_tool", state.taint_source_tool)

        # Compact if crossing the N-tool-call mark
        if state.tool_calls_count > 0 and state.tool_calls_count % compact_every == 0:
            from .compaction import compact_messages
            state.messages = await compact_messages(state.messages, state.artifact_refs)

        # Retrieve context if in a scoped mode
        chunks, examples, anchors = await _load_scoped_context(scope, task, state)

        # Build system prompt blocks
        system_blocks = compose_system(
            scope=scope, task=task, mode=state.mode,
            retrieved_chunks=chunks, examples=examples, style_anchors=anchors,
        )

        # Pick model tier
        tier = _pick_tier(state, scope)

        # Call model
        with otel.span("agent.turn"):
            result = await model().generate(
                system=system_blocks,
                messages=state.messages,
                tools=anthropic_tool_defs(scope),
                tier=tier,
                job_id=job_id,
                max_tokens=4096,
            )
        # Note: cost is authoritative via cost_ledger; in-memory cost_usd
        # is just a local tally and should NOT be written back to jobs.cost_usd.
        state.cost_usd += result.cost_usd

        if result.stop_reason == "end_turn" and not result.tool_uses:
            state.final_text = result.text
            state.done = True
            if not _save_checkpoint_sync(state, worker_id=worker_id):
                raise LeaseLost(job_id)
            break

        # Append the assistant turn to messages
        state.messages.append({"role": "assistant", "content": result.raw_content})

        # Execute tool uses — parallel when independent.
        # H2: skip tool_use_ids that completed in a prior run
        fresh_tool_uses = [
            tu for tu in result.tool_uses if tu.get("id") not in already_executed_ids
        ]
        skipped_count = len(result.tool_uses) - len(fresh_tool_uses)
        if skipped_count:
            log.info("agent.resume.dedup", job_id=job_id, skipped=skipped_count)
        tool_result_blocks = await _execute_tool_uses(job_id, scope, state, fresh_tool_uses)
        # Rebuild full result list maintaining order, filling skipped with
        # synthetic "already executed" markers so message ordering stays sane
        full_results = []
        fresh_iter = iter(tool_result_blocks)
        for tu in result.tool_uses:
            if tu.get("id") in already_executed_ids:
                full_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu["id"],
                    "content": json.dumps({"replayed": True, "note": "completed in prior run"}),
                    "is_error": False,
                })
            else:
                full_results.append(next(fresh_iter))
        state.messages.append({"role": "user", "content": full_results})

        state.tool_calls_count += len(result.tool_uses)
        # Clear the dedup set after first successful batch — from here on it's a fresh run
        already_executed_ids = set()
        if not _save_checkpoint_sync(state, worker_id=worker_id):
            raise LeaseLost(job_id)

    # Mark done if we exhausted tool calls without end_turn
    if not state.done:
        state.final_text = state.final_text or (
            "I hit the tool-call budget for this job without reaching a final "
            f"answer. Partial progress saved. Tool calls used: {state.tool_calls_count}."
        )

    if not _finish_job(job_id, state, worker_id=worker_id):
        raise LeaseLost(job_id)


def _already_executed_tool_use_ids(state: JobState) -> set[str]:
    """Scan the state's message history for tool_use_ids that already have a
    matching tool_result — those are safe to skip on resume (H2)."""
    result_ids: set[str] = set()
    for msg in state.messages:
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id")
                    if tid:
                        result_ids.add(tid)
    return result_ids


# ---------- helpers --------------------------------------------------------


async def _load_scoped_context(scope: str, task: str, state: JobState):
    """Retrieve chunks/examples/anchors as appropriate for the scope and mode."""
    if scope == "orchestrator":
        return [], [], []
    # For scoped agents (author personas), pull in corpus context
    from ..modes.retrieval import retrieve_knowledge

    chunks_res = await retrieve_knowledge(scope=scope, query=task, top_k=8)
    anchors_res = await retrieve_knowledge(scope=scope, query=task, top_k=4, style_anchors_only=True)
    # examples: would query agent_examples by similarity; stub for v1
    return chunks_res.get("chunks", []), [], anchors_res.get("chunks", [])


def _pick_tier(state: JobState, scope: str) -> ModelTier:
    """v1 model-tier routing: Sonnet default, Haiku for trivial chat triage,
    Opus when the user or prompt has explicitly asked for hard thinking.
    Orchestrator LLM is also nudged by its system prompt to signal tier needs."""
    # Simple heuristic: if we've already made many tool calls, stay on strong
    return ModelTier.STRONG


async def _execute_tool_uses(
    job_id: str, scope: str, state: JobState, tool_uses: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Run each tool_use (in parallel), return the matching tool_result blocks.

    C3 defense — parallel taint race: if ANY tool in this batch is taint-marking,
    we pessimistically set state.tainted = True BEFORE any tool in the batch
    runs. Otherwise a write tool (e.g. `remember`) could race a tainting read
    (e.g. `fetch_url`) and have its consent evaluated against a clean state.
    """
    # Pre-scan: pessimistic taint BEFORE any tool in the batch executes.
    for tu in tool_uses:
        e = REGISTRY.get(tu.get("name", ""))
        if e is not None and e.taints_job and not state.tainted:
            state.tainted = True
            state.taint_source_tool = f"batch:{e.name}"
            otel.set_attr("agent.job.tainted", True)
            otel.set_attr("agent.taint.source_tool", state.taint_source_tool)
            break

    async def run_one(tu: dict[str, Any]) -> dict[str, Any]:
        name = tu["name"]
        args = tu.get("input", {}) or {}
        entry = REGISTRY.get(name)
        if entry is None:
            return _err_block(tu["id"], f"tool {name} not registered")

        # Agent ACL
        if "*" not in entry.agents and scope not in entry.agents:
            return _err_block(tu["id"], f"tool {name} not allowed for scope {scope}")

        # Consent
        consent_res = await consent_mod.check(
            job_id=job_id, entry=entry, arguments=args, tainted=state.tainted,
        )
        if not consent_res.approved:
            return _err_block(tu["id"], f"user declined ({consent_res.reason})")

        # Inject job_id into kwargs for tools that accept it
        import inspect
        sig = inspect.signature(entry.fn)
        if "job_id" in sig.parameters and "job_id" not in args:
            args["job_id"] = job_id
        if "agent_scope" in sig.parameters and "agent_scope" not in args and scope != "orchestrator":
            args["agent_scope"] = scope
        if "tainted" in sig.parameters and "tainted" not in args:
            args["tainted"] = state.tainted

        # Execute
        t0 = time.perf_counter()
        with otel.span(
            f"agent.tool.{name}",
            **{
                "agent.tool.name": name,
                "agent.tool.scope": entry.scope,
                "agent.tool.cost": entry.cost,
                "agent.job.id": job_id,
            },
        ):
            try:
                result = await entry.fn(**args)
                status = "done"
                error = None
            except Exception as e:  # noqa: BLE001
                log.exception("agent.tool.error", tool=name, error=str(e))
                result = {"error": str(e)}
                status = "error"
                error = str(e)

        duration_ms = int((time.perf_counter() - t0) * 1000)

        # Update taint — either the tool is statically taint-marking, OR its
        # result explicitly reports tainted=True (e.g., read_artifact reading
        # a tainted artifact). Both cases propagate onto the job.
        result_tainted = (
            isinstance(result, dict) and bool(result.get("tainted"))
        )
        if (entry.taints_job or result_tainted) and not state.tainted:
            state.tainted = True
            state.taint_source_tool = name
            otel.set_attr("agent.job.tainted", True)
            otel.set_attr("agent.taint.source_tool", name)

        # Log to tool_calls
        conn = connect()
        try:
            tool_calls_mod.insert_tool_call(
                conn, job_id=job_id, tool_name=name, arguments=args,
                result=result if isinstance(result, (dict, list, str)) else str(result),
                duration_ms=duration_ms,
                idempotent=entry.idempotent, tainted=state.tainted,
                status=status, error=error,
            )
        finally:
            conn.close()

        # Track artifact refs for compaction
        if isinstance(result, dict) and "artifact_id" in result:
            state.artifact_refs.append(str(result["artifact_id"]))

        return {
            "type": "tool_result",
            "tool_use_id": tu["id"],
            "content": json.dumps(result, default=str) if not isinstance(result, str) else result,
            "is_error": status == "error",
        }

    results = await asyncio.gather(*[run_one(tu) for tu in tool_uses])
    return list(results)


def _err_block(tool_use_id: str, msg: str) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps({"error": msg}),
        "is_error": True,
    }


def _save_checkpoint_sync(state: JobState, *, worker_id: str | None = None) -> bool:
    """Guarded checkpoint write. Returns False if the lease has been lost."""
    conn = connect()
    try:
        with transaction(conn):
            return jobs_mod.save_checkpoint(
                conn, state.job_id,
                state=state.to_dict(),
                tainted=state.tainted,
                taint_source_tool=state.taint_source_tool,
                tool_call_count=state.tool_calls_count,
                worker_id=worker_id,
            )
    finally:
        conn.close()


def _finish_job(job_id: str, state: JobState, *, worker_id: str | None = None) -> bool:
    """Guarded final write + DONE transition. Returns False if the lease was lost."""
    conn = connect()
    try:
        with transaction(conn):
            ok1 = jobs_mod.save_checkpoint(
                conn, job_id,
                state=state.to_dict(),
                tainted=state.tainted,
                taint_source_tool=state.taint_source_tool,
                tool_call_count=state.tool_calls_count,
                worker_id=worker_id,
            )
            if not ok1:
                return False
            ok2 = jobs_mod.set_status(conn, job_id, JobStatus.DONE, worker_id=worker_id)
            return ok2
    finally:
        conn.close()


class JobRenewer:
    """Lease heartbeat helper — worker pings this between tool calls."""

    def __init__(self, job_id: str, worker_id: str):
        self.job_id = job_id
        self.worker_id = worker_id

    def beat(self) -> None:
        conn = connect()
        try:
            jobs_mod.renew_lease(conn, self.job_id, self.worker_id)
        finally:
            conn.close()
