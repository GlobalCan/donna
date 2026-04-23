"""SQLite connection management.

Two-process contract:
 - `bot` process opens in 'enqueue' mode: inserts messages, jobs, permission_grants.
   Never writes to job lease columns, tool_calls, traces, or checkpoint_state.
 - `worker` process is the sole owner of lease/heartbeat/checkpoint writes.

Both open the same file in WAL mode. SQLite's WAL handles the single-writer +
multi-reader case; our discipline avoids contention over the job table's hot path.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import sqlite_vec

from ..config import settings
from ..logging import get_logger

log = get_logger(__name__)

_PRAGMAS = [
    "PRAGMA journal_mode = WAL",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA wal_autocheckpoint = 1000",
    "PRAGMA foreign_keys = ON",
    "PRAGMA temp_store = MEMORY",
]


# --- datetime adapter registration (Python 3.12+ compat) -------------------
# Python 3.12 deprecated the default datetime adapter. Register explicit
# ISO-8601 adapters so every Connection serializes consistently. Naive
# datetimes are assumed UTC (we use `datetime.now(timezone.utc)` everywhere).
# Readers parse back via `datetime.fromisoformat` (see memory.jobs._dt and
# peer modules).


def _adapt_datetime_iso(val: datetime) -> str:
    if val.tzinfo is None:
        val = val.replace(tzinfo=UTC)
    # Space separator keeps SQLite's built-in date()/datetime() happy while
    # `datetime.fromisoformat` still parses it on read.
    return val.isoformat(sep=" ")


def _adapt_date_iso(val: date) -> str:
    return val.isoformat()


sqlite3.register_adapter(datetime, _adapt_datetime_iso)
sqlite3.register_adapter(date, _adapt_date_iso)


def _prepare_connection(conn: sqlite3.Connection) -> None:
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    # Load sqlite-vec extension for vector search
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    conn.row_factory = sqlite3.Row


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a new connection with all pragmas + sqlite-vec loaded."""
    db_path = path or settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=30.0)
    _prepare_connection(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit BEGIN/COMMIT wrapper; rolls back on exception."""
    conn.execute("BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def initialize_if_empty(conn: sqlite3.Connection) -> None:
    """Apply alembic migrations programmatically if no tables exist yet.

    For container/dev convenience — in prod, migrations run from alembic CLI.
    """
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()
    if row is None:
        log.info("db.empty — run `alembic upgrade head` to create schema")
