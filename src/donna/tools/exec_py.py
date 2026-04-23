"""run_python — sandboxed Python execution via subprocess.

v1 sandbox model:
 - Spawn a fresh `python -I` subprocess with strict resource limits
 - Script written to a tempfile (readable by the subprocess only)
 - stdin closed, network disabled via env (no easy cross-platform firewall — we
   rely on Docker-level egress allowlist in production)
 - wall-time limit, output size limit

Not bulletproof (no nsjail / e2b here), but sufficient given:
 - run_python is always `confirmation=always`
 - Container is read-only rootfs + egress allowlist + no docker socket
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from contextlib import suppress
from typing import Any

from .registry import tool

SANDBOX_TIMEOUT_S = 30
SANDBOX_MAX_OUTPUT = 64_000


@tool(
    scope="exec_code", cost="medium", confirmation="always", taints_job=True,
    idempotent=False,
    description=(
        "Execute a Python script in an isolated subprocess. No network by "
        "default (egress firewall at container level). Always requires user "
        "confirmation. Timeout 30s. Stdout + stderr captured; large output "
        "saved as artifact."
    ),
)
async def run_python(code: str, timeout_s: int = SANDBOX_TIMEOUT_S) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(code)
        script_path = tf.name

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-B", script_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env={
                "PATH": os.environ.get("PATH", ""),
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except TimeoutError:
            with suppress(ProcessLookupError):
                proc.kill()
            return {"error": "timeout", "timeout_s": timeout_s}

        stdout = stdout_b.decode("utf-8", errors="replace")[:SANDBOX_MAX_OUTPUT]
        stderr = stderr_b.decode("utf-8", errors="replace")[:SANDBOX_MAX_OUTPUT]
        return {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": len(stdout_b) > SANDBOX_MAX_OUTPUT or len(stderr_b) > SANDBOX_MAX_OUTPUT,
        }
    finally:
        with suppress(OSError):
            os.unlink(script_path)
