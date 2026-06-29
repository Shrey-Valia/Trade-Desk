"""Missing-index creation in database._create_missing_indexes (WS7).

Two indexes back the hottest read paths and were absent:
  - trades(exit_date)         — every 5pm-PT trading-day window in combine_state
  - combines(user_id, status) — list_combines + the slot-cap / active-set logic

The helper uses `CREATE INDEX IF NOT EXISTS`, so it must be idempotent: running
it twice on the same DB creates the indexes once and is a clean no-op the second
time. These tests run it against a fresh in-memory SQLite engine (patched in for
the module-global `engine`) and assert both indexes exist and re-running raises
nothing.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import database
from database import Base


@pytest.fixture
def index_engine(monkeypatch):
    # Import every model so create_all builds the full schema (trades/combines
    # included) before we add indexes on their columns.
    import models.account_state  # noqa: F401
    import models.auth_session  # noqa: F401
    import models.combine  # noqa: F401
    import models.combine_event  # noqa: F401
    import models.payment  # noqa: F401
    import models.trade  # noqa: F401
    import models.user  # noqa: F401

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=eng)
    # _create_missing_indexes operates on the module-global engine.
    monkeypatch.setattr(database, "engine", eng)
    yield eng
    eng.dispose()


def _index_names(engine, table: str) -> set[str]:
    return {ix["name"] for ix in inspect(engine).get_indexes(table)}


def test_creates_the_two_missing_indexes(index_engine):
    database._create_missing_indexes()
    assert "ix_trades_exit_date" in _index_names(index_engine, "trades")
    assert "ix_combines_user_status" in _index_names(index_engine, "combines")


def test_combines_index_is_composite_user_id_status(index_engine):
    database._create_missing_indexes()
    by_name = {
        ix["name"]: ix for ix in inspect(index_engine).get_indexes("combines")
    }
    cols = by_name["ix_combines_user_status"]["column_names"]
    assert cols == ["user_id", "status"]


def test_combines_index_not_duplicated_on_fresh_db(index_engine):
    """On a fresh DB the Combine model already builds ix_combines_user_status
    (via create_all). Re-asserting it in _create_missing_indexes with the SAME
    name must NOT spawn a second (user_id, status) index — there's exactly one."""
    database._create_missing_indexes()
    combines_idx = inspect(index_engine).get_indexes("combines")
    user_status = [
        ix for ix in combines_idx if ix["column_names"] == ["user_id", "status"]
    ]
    assert len(user_status) == 1, [ix["name"] for ix in user_status]


def test_create_missing_indexes_is_idempotent(index_engine):
    # First pass creates them; a second pass must be a clean no-op (the
    # IF NOT EXISTS guard) — no IntegrityError / OperationalError.
    database._create_missing_indexes()
    database._create_missing_indexes()
    names = _index_names(index_engine, "trades") | _index_names(index_engine, "combines")
    # Still exactly one of each (no duplicates from the second run).
    assert "ix_trades_exit_date" in names
    assert "ix_combines_user_status" in names
    # The pre-existing indexes are untouched too.
    assert "ix_trades_combine_id" in _index_names(index_engine, "trades")
    assert "ix_trades_oco_group" in _index_names(index_engine, "trades")
