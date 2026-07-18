"""database._additive_migrate_trades — the pre-tier wipe boot guard.

A `trades` table MISSING the 'tier' column is almost always a restored
pre-tier backup, and the legacy migration used to silently DELETE every
row. The guard now refuses to boot when the table is populated unless
ALLOW_LEGACY_TRADE_WIPE=1; an empty table (nothing to lose) and the
explicit flag preserve the original adoption behavior.

Tests point database.engine at a tmp_path SQLite file — the real data/
directory is never touched.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text

import database
from config import settings


@pytest.fixture
def legacy_engine(tmp_path, monkeypatch):
    """A tmp-file DB whose `trades` table PRE-DATES the tier column, wired
    in as database.engine so _additive_migrate_trades runs against it."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE trades ("
                "id INTEGER PRIMARY KEY, symbol TEXT, status TEXT)"
            )
        )
    monkeypatch.setattr(database, "engine", engine)
    yield engine
    engine.dispose()


def _trade_columns(engine) -> set[str]:
    return {col["name"] for col in inspect(engine).get_columns("trades")}


def _row_count(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM trades")).scalar() or 0


def test_empty_pretier_table_migrates_without_flag(legacy_engine):
    assert not settings.allow_legacy_trade_wipe  # the shipped default
    database._additive_migrate_trades()

    cols = _trade_columns(legacy_engine)
    assert "tier" in cols
    assert "combine_id" in cols
    assert _row_count(legacy_engine) == 0


def test_populated_pretier_table_refuses_to_boot(legacy_engine):
    with legacy_engine.begin() as conn:
        conn.execute(text("INSERT INTO trades (symbol, status) VALUES ('SPY', 'closed')"))

    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        database._additive_migrate_trades()

    # The refusal must leave the database byte-for-byte untouched: no rows
    # deleted, no columns added (the guard fires before any ALTER).
    assert _row_count(legacy_engine) == 1
    assert "tier" not in _trade_columns(legacy_engine)


def test_refusal_message_names_the_escape_hatch(legacy_engine):
    with legacy_engine.begin() as conn:
        conn.execute(text("INSERT INTO trades (symbol, status) VALUES ('SPY', 'closed')"))

    with pytest.raises(RuntimeError) as excinfo:
        database._additive_migrate_trades()

    msg = str(excinfo.value)
    assert "ALLOW_LEGACY_TRADE_WIPE" in msg
    assert "backup" in msg.lower()


def test_flag_preserves_the_one_time_adoption_wipe(legacy_engine, monkeypatch):
    with legacy_engine.begin() as conn:
        conn.execute(text("INSERT INTO trades (symbol, status) VALUES ('SPY', 'closed')"))
        conn.execute(text("INSERT INTO trades (symbol, status) VALUES ('QQQ', 'open')"))
    monkeypatch.setattr(settings, "allow_legacy_trade_wipe", True)

    database._additive_migrate_trades()

    assert "tier" in _trade_columns(legacy_engine)
    assert _row_count(legacy_engine) == 0  # legacy rows wiped, as before


def test_post_tier_table_never_trips_the_guard(legacy_engine):
    """A table that already has `tier` (i.e. any current DB) migrates any
    OTHER pending columns without ever entering the wipe branch."""
    with legacy_engine.begin() as conn:
        conn.execute(text("ALTER TABLE trades ADD COLUMN tier VARCHAR(8) NOT NULL DEFAULT '50K'"))
        conn.execute(text("INSERT INTO trades (symbol, status) VALUES ('SPY', 'closed')"))

    database._additive_migrate_trades()  # must not raise

    assert _row_count(legacy_engine) == 1  # rows preserved
    assert "combine_id" in _trade_columns(legacy_engine)
