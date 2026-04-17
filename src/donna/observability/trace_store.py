"""SqliteSpanProcessor — persist finished spans to the `traces` table.

Codex review #13 caught that the `traces` table had no writer — Phoenix was
the only consumer. This processor writes a compact row per finished span so
SQL queries (and `botctl traces prune`) have something to work with, and
traces survive Phoenix retention.
"""
from __future__ import annotations

import json

from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

from ..logging import get_logger
from ..memory import ids as ids_mod
from ..memory.db import connect

log = get_logger(__name__)


class SqliteSpanProcessor(SpanProcessor):
    def on_start(self, span, parent_context=None) -> None:  # noqa: D401
        """No-op — we only record completed spans."""
        return None

    def on_end(self, span: ReadableSpan) -> None:
        try:
            attrs = dict(span.attributes or {})
        except Exception:
            attrs = {}
        job_id = attrs.get("agent.job.id")
        tainted = bool(attrs.get("agent.job.tainted"))

        start_ns = span.start_time or 0
        end_ns = span.end_time or start_ns
        duration_ms = max(0, int((end_ns - start_ns) / 1_000_000))

        parent_span_id = None
        if span.parent is not None:
            parent_span_id = format(span.parent.span_id, "016x")

        try:
            conn = connect()
            try:
                conn.execute(
                    """
                    INSERT INTO traces
                        (id, job_id, span_name, parent_span, attributes, started_at,
                         duration_ms, tainted)
                    VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?)
                    """,
                    (
                        ids_mod.trace_id(), job_id, span.name, parent_span_id,
                        json.dumps({k: _safe(v) for k, v in attrs.items()}, default=str),
                        duration_ms, 1 if tainted else 0,
                    ),
                )
            finally:
                conn.close()
        except Exception as e:  # noqa: BLE001
            # Never raise from a span processor — we'd lose the span
            log.debug("trace_store.write_failed", error=str(e))

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:  # noqa: D401
        return True


def _safe(v):
    try:
        json.dumps(v)
        return v
    except Exception:
        return str(v)
