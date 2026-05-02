"""V0.6 #6: migration policy linter.

Enforces the structural parts of `docs/SCHEMA_LIFECYCLE.md`. Run as part
of the regular pytest suite — a new migration that violates the policy
fails CI before merge.

Catches:
  - Missing or wrong-format revision id
  - Broken down_revision chain (gaps or branches)
  - Missing module docstring
  - Missing upgrade()/downgrade()
  - Branch labels accidentally set (we don't use branches)
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"

REV_ID_RE = re.compile(r"^\d{4}$")
FILE_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.py$")


def _migration_files() -> list[Path]:
    return sorted(
        p for p in MIGRATIONS_DIR.iterdir()
        if p.is_file() and p.suffix == ".py" and not p.name.startswith("_")
    )


def _load_migration_module(path: Path):
    """Import a migration file as a module without alembic running it."""
    spec = importlib.util.spec_from_file_location(
        f"_test_migration_{path.stem}", path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"can't load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migrations() -> list[tuple[str, object, Path]]:
    """Return [(rev_id, module, path), ...] sorted by revision."""
    out = []
    for path in _migration_files():
        m = _load_migration_module(path)
        out.append((getattr(m, "revision", None), m, path))
    out.sort(key=lambda t: t[0] or "")
    return out


# ---------- file naming + module attributes ------------------------------


def test_every_migration_filename_matches_pattern() -> None:
    """`NNNN_lower_snake_case.py` (e.g. `0009_outbox_dead_letter.py`)."""
    bad = []
    for path in _migration_files():
        if not FILE_RE.match(path.name):
            bad.append(path.name)
    assert not bad, (
        f"migration file names must match NNNN_<lower_snake>.py — bad: {bad}"
    )


def test_every_migration_has_required_attributes(
    migrations: list,
) -> None:
    """alembic needs revision / down_revision / branch_labels /
    depends_on at module top-level."""
    for rev, m, path in migrations:
        for attr in ("revision", "down_revision", "branch_labels", "depends_on"):
            assert hasattr(m, attr), (
                f"{path.name}: missing module attribute `{attr}`"
            )


def test_revision_ids_are_4_digit_zero_padded(migrations: list) -> None:
    """Zero-padding lets `version >= '0008'` string-compare correctly
    in the backup verifier and other policy gates."""
    for rev, m, path in migrations:
        assert isinstance(rev, str), (
            f"{path.name}: revision must be a str (got {type(rev).__name__})"
        )
        assert REV_ID_RE.match(rev), (
            f"{path.name}: revision {rev!r} must be 4-digit zero-padded numeric"
        )


def test_revision_id_matches_filename_prefix(migrations: list) -> None:
    """Filename `NNNN_*.py` and `revision = 'NNNN'` must agree."""
    for rev, m, path in migrations:
        prefix = path.name[:4]
        assert prefix == rev, (
            f"{path.name}: filename prefix {prefix!r} != revision {rev!r}"
        )


def test_no_branch_labels(migrations: list) -> None:
    """We don't use alembic branches. Setting branch_labels is a footgun
    — alembic gets opinions about merge directives that the project
    doesn't need."""
    for rev, m, path in migrations:
        assert m.branch_labels is None, (
            f"{path.name}: branch_labels = {m.branch_labels!r}; must be None"
        )


# ---------- chain integrity ----------------------------------------------


def test_first_migration_has_no_predecessor(migrations: list) -> None:
    """0001 has down_revision = None. Anything else means a missing
    bootstrap or a chain break."""
    assert migrations, "no migrations found"
    first_rev, m, path = migrations[0]
    assert first_rev == "0001", (
        f"first migration must be 0001, got {first_rev!r} ({path.name})"
    )
    assert m.down_revision is None, (
        f"{path.name}: down_revision must be None for migration 0001"
    )


def test_revision_chain_has_no_gaps_or_branches(migrations: list) -> None:
    """Every migration NNNN has down_revision pointing to (NNNN-1).
    Gaps mean a missing migration; branches mean two migrations claim
    the same parent (alembic can handle this with merge directives but
    we explicitly don't allow it)."""
    seen_down: set[str] = set()
    for i, (rev, m, path) in enumerate(migrations):
        if i == 0:
            continue
        expected_parent = f"{int(rev) - 1:04d}"
        assert m.down_revision == expected_parent, (
            f"{path.name}: down_revision = {m.down_revision!r}, "
            f"expected {expected_parent!r} (revision {rev} should follow "
            f"{expected_parent})"
        )
        assert m.down_revision not in seen_down, (
            f"{path.name}: parent {m.down_revision!r} already claimed by "
            f"another migration (branch)"
        )
        seen_down.add(m.down_revision)


def test_no_duplicate_revision_ids(migrations: list) -> None:
    revs = [rev for rev, _, _ in migrations]
    dupes = [r for r in set(revs) if revs.count(r) > 1]
    assert not dupes, f"duplicate revision ids: {dupes}"


# ---------- callable shape -----------------------------------------------


def test_every_migration_has_upgrade_and_downgrade(migrations: list) -> None:
    for rev, m, path in migrations:
        assert callable(getattr(m, "upgrade", None)), (
            f"{path.name}: upgrade() missing or not callable"
        )
        assert callable(getattr(m, "downgrade", None)), (
            f"{path.name}: downgrade() missing or not callable"
        )


def test_module_has_non_empty_docstring(migrations: list) -> None:
    """Every migration must explain WHY in its docstring. Short
    one-liners are acceptable but blank is not."""
    for rev, m, path in migrations:
        doc = (m.__doc__ or "").strip()
        assert doc, f"{path.name}: missing module docstring (the WHY)"
        assert len(doc) > 20, (
            f"{path.name}: docstring is suspiciously short "
            f"({len(doc)} chars). Lead with the WHY: incident, feature, "
            f"or refactor that motivated this change."
        )
