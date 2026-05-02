"""Shared types — Job, JobState, ToolEntry, Message, etc."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class ModelTier(StrEnum):
    FAST = "fast"        # Haiku
    STRONG = "strong"    # Sonnet
    HEAVY = "heavy"      # Opus


class ConfirmationMode(StrEnum):
    NEVER = "never"
    ONCE_PER_JOB = "once_per_job"
    ALWAYS = "always"
    HIGH_IMPACT_ALWAYS = "high_impact_always"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED_AWAITING_CONSENT = "paused_awaiting_consent"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobMode(StrEnum):
    CHAT = "chat"
    GROUNDED = "grounded"
    SPECULATIVE = "speculative"
    DEBATE = "debate"
    VALIDATE = "validate"        # v0.7.1 URL-bounded grounded critique


@dataclass
class ToolEntry:
    name: str
    fn: Callable[..., Awaitable[Any]]
    schema: dict[str, Any]
    description: str
    scope: str                   # e.g. "read_web", "write_memory"
    cost: str                    # "low" | "medium" | "high"
    confirmation: ConfirmationMode
    taints_job: bool
    idempotent: bool
    agents: tuple[str, ...]      # ("*",) or ("researcher","analyst")


@dataclass
class Message:
    role: str                    # user | assistant | tool
    content: Any                 # text, or list of content blocks


@dataclass
class JobState:
    """In-memory state for a single job's loop. Persisted as JSON via checkpoint."""
    job_id: str
    agent_scope: str
    mode: JobMode
    tainted: bool = False
    taint_source_tool: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls_count: int = 0
    artifact_refs: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    done: bool = False
    final_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "agent_scope": self.agent_scope,
            "mode": self.mode.value,
            "tainted": self.tainted,
            "taint_source_tool": self.taint_source_tool,
            "messages": self.messages,
            "tool_calls_count": self.tool_calls_count,
            "artifact_refs": self.artifact_refs,
            "cost_usd": self.cost_usd,
            "done": self.done,
            "final_text": self.final_text,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JobState:
        return cls(
            job_id=d["job_id"],
            agent_scope=d["agent_scope"],
            mode=JobMode(d.get("mode", "chat")),
            tainted=d.get("tainted", False),
            taint_source_tool=d.get("taint_source_tool"),
            messages=d.get("messages", []),
            tool_calls_count=d.get("tool_calls_count", 0),
            artifact_refs=d.get("artifact_refs", []),
            cost_usd=d.get("cost_usd", 0.0),
            done=d.get("done", False),
            final_text=d.get("final_text"),
        )


@dataclass
class Job:
    id: str
    agent_scope: str
    task: str
    mode: JobMode
    status: JobStatus
    thread_id: str | None
    priority: int
    owner: str | None
    lease_until: datetime | None
    checkpoint_state: dict[str, Any] | None
    tainted: bool
    cost_usd: float
    tool_call_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    model_tier_override: str | None = None   # v1.1 /model command support
    schedule_id: str | None = None           # v0.6.3 schedule back-link


@dataclass
class Chunk:
    """Retrieved knowledge chunk."""
    id: str
    source_id: str
    agent_scope: str
    work_id: str | None
    publication_date: str | None
    source_type: str
    content: str
    score: float
    chunk_index: int
    is_style_anchor: bool
    source_title: str | None = None
