"""Pytest fixtures — spin up an isolated SQLite DB for each test."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setenv("DONNA_DATA_DIR", d)
        monkeypatch.setenv("DONNA_ENV", "dev")
        # dummies so config validation passes
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
        monkeypatch.setenv("DISCORD_BOT_TOKEN", "test")
        monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "0")
        monkeypatch.setenv("TAVILY_API_KEY", "test")
        monkeypatch.setenv("VOYAGE_API_KEY", "test")

        # Reset the cached settings singleton
        from donna import config as cfg_mod
        cfg_mod._settings = None

        yield Path(d)


@pytest.fixture
def fresh_db() -> None:
    """Run migrations on the isolated DB.

    Invoke alembic via the current Python interpreter (`-m alembic`) rather
    than by name — on Windows the venv's alembic.exe isn't on the subprocess
    PATH unless the venv is activated in the parent shell, which it often
    isn't when pytest runs directly via `.venv/Scripts/python -m pytest`.
    """
    import subprocess
    import sys
    subprocess.check_call(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parent.parent,
    )
