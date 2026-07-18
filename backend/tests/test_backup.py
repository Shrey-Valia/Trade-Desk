"""jobs/backup_db — nightly SQLite snapshot + retention pruning.

Everything runs against tmp_path SQLite files; the real data/ directory is
never touched. prune_job_runs is stubbed because the real one opens a
session on the app's live engine.
"""

from __future__ import annotations

import os
import sqlite3
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from jobs.backup_db import backup_db


@pytest.fixture(autouse=True)
def _stub_prune_job_runs(monkeypatch):
    """Keep the JobRun prune off the app's real database. Records calls so
    tests can assert the backup job actually invoked it."""
    calls: list[int] = []

    def fake_prune(days: int = 14) -> int:
        calls.append(days)
        return 7

    monkeypatch.setattr("services.job_runs.prune_job_runs", fake_prune)
    return calls


@pytest.fixture
def seeded_engine(tmp_path):
    """A tmp-file SQLite engine with a seeded table (stands in for the live DB)."""
    db_file = tmp_path / "live.db"
    engine = create_engine(f"sqlite:///{db_file}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT)"))
        conn.execute(
            text("INSERT INTO trades (symbol) VALUES ('SPY'), ('QQQ'), ('IWM')")
        )
        conn.execute(text("CREATE TABLE combines (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO combines (id) VALUES (1)"))
    yield engine
    engine.dispose()


def _sqlite_tables(path) -> set[str]:
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {r[0] for r in rows}


def test_backup_creates_consistent_snapshot(seeded_engine, tmp_path, _stub_prune_job_runs):
    backup_dir = tmp_path / "backups"

    result = backup_db(engine=seeded_engine, backup_dir=str(backup_dir), retention_days=14)

    assert result["status"] == "ok"
    dest = result["file"]
    assert os.path.isfile(dest)
    assert os.path.basename(dest).startswith("dashboard-")
    assert dest.endswith(".db")

    # Same tables, same row counts as the source.
    assert _sqlite_tables(dest) >= {"trades", "combines"}
    with sqlite3.connect(dest) as conn:
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM combines").fetchone()[0] == 1
        symbols = {r[0] for r in conn.execute("SELECT symbol FROM trades").fetchall()}
    assert symbols == {"SPY", "QQQ", "IWM"}

    # JobRun pruning ran and its count is surfaced.
    assert _stub_prune_job_runs == [14]
    assert result["pruned_job_runs"] == 7
    assert result["pruned_backups"] == 0


def test_backup_safe_while_source_has_open_writer(seeded_engine, tmp_path):
    """The .backup API must produce a complete snapshot even with another
    live connection on the source (the scheduler runs alongside writers)."""
    other = seeded_engine.connect()
    try:
        other.execute(text("INSERT INTO trades (symbol) VALUES ('TLT')"))
        other.commit()
        result = backup_db(
            engine=seeded_engine, backup_dir=str(tmp_path / "b"), retention_days=14
        )
    finally:
        other.close()

    with sqlite3.connect(result["file"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 4


def test_retention_prunes_only_old_backup_files(seeded_engine, tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    old = backup_dir / "dashboard-20200101-000000.db"
    old.write_bytes(b"stale")
    hundred_days_ago = time.time() - 100 * 86_400
    os.utime(old, (hundred_days_ago, hundred_days_ago))

    recent = backup_dir / "dashboard-20990101-000000.db"
    recent.write_bytes(b"fresh")

    # A non-backup file in the directory must never be touched, however old.
    manual = backup_dir / "manual-copy.sqlite"
    manual.write_bytes(b"keep me")
    os.utime(manual, (hundred_days_ago, hundred_days_ago))

    result = backup_db(engine=seeded_engine, backup_dir=str(backup_dir), retention_days=14)

    assert result["status"] == "ok"
    assert result["pruned_backups"] == 1
    assert not old.exists()
    assert recent.exists()
    assert manual.exists()
    assert os.path.isfile(result["file"])


def test_noop_on_non_sqlite_engine(tmp_path):
    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    result = backup_db(engine=fake_engine, backup_dir=str(tmp_path / "b"), retention_days=14)

    assert result["status"] == "skipped"
    assert "postgresql" in result["reason"]
    # Skip path must not create the backup directory or any files.
    assert not (tmp_path / "b").exists()
