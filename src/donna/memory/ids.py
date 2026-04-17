"""ID generation — short, sortable, typed prefixes."""
from __future__ import annotations

import base64
import secrets
import time


def _b32() -> str:
    # 10 bytes → 16 char base32 (no padding), lowercase
    return base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=").lower()


def new_id(prefix: str) -> str:
    """e.g. new_id('job') -> 'job_abc123...'."""
    ts = int(time.time())
    return f"{prefix}_{ts:x}_{_b32()[:10]}"


def job_id() -> str: return new_id("job")
def thread_id() -> str: return new_id("thr")
def message_id() -> str: return new_id("msg")
def tool_call_id() -> str: return new_id("tc")
def trace_id() -> str: return new_id("trc")
def fact_id() -> str: return new_id("fact")
def artifact_id() -> str: return new_id("art")
def grant_id() -> str: return new_id("grt")
def schedule_id() -> str: return new_id("sch")
def source_id() -> str: return new_id("src")
def chunk_id() -> str: return new_id("chk")
def heuristic_id() -> str: return new_id("h")
def example_id() -> str: return new_id("ex")
def prompt_id() -> str: return new_id("pmt")
def cost_id() -> str: return new_id("cost")
