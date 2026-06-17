"""Rule enforcement on the trade-open path + the scheduled settlement job.

Covers the two halves of "make the rules real": _require_tradeable() (the
server-side open gate) and settle_combines() (the clock-driven auto-fail /
settlement that no longer waits for a read)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import models.combine_event  # noqa: F401 — ensure combine_events table is created
from jobs.settle_combines import settle_combines
from models.combine import Combine
from models.combine_event import CombineEvent
from models.trade import Trade
from routers import zerodte
from tests.conftest import make_combine


def _seed_closed_trade(session, combine_id: int, realized: float) -> None:
    now = datetime.now(timezone.utc)
    session.add(
        Trade(
            symbol="SPY",
            strategy="long_call",
            entry_date=now,
            entry_underlying_price=400.0,
            net_debit_credit=0.0,
            status="closed",
            is_paper=True,
            notes="seed",
            tier="50K",
            combine_id=combine_id,
            exit_date=now,
            exit_underlying_price=400.0,
            realized_pnl=realized,
            legs_json="[]",
        )
    )
    session.commit()


def test_settle_combines_auto_fails_on_mll_breach(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    session = session_factory()
    # -2_500 → balance 47_500 ≤ 48_000 floor.
    _seed_closed_trade(session, c["id"], -2_500.0)
    session.close()

    summary = settle_combines(session_factory=session_factory)
    assert summary["processed"] >= 1
    assert summary["failed"] == 0

    session = session_factory()
    combine = session.get(Combine, c["id"])
    assert combine.outcome == "failed"
    events = (
        session.execute(
            select(CombineEvent).where(
                CombineEvent.combine_id == c["id"], CombineEvent.type == "failed"
            )
        )
        .scalars()
        .all()
    )
    assert len(events) >= 1
    session.close()


def test_settle_combines_leaves_healthy_combine_active(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    session = session_factory()
    _seed_closed_trade(session, c["id"], 250.0)  # small win, no breach
    session.close()

    settle_combines(session_factory=session_factory)

    session = session_factory()
    assert session.get(Combine, c["id"]).outcome == "active"
    session.close()


def test_require_tradeable_blocks_failed_combine(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    session = session_factory()
    _seed_closed_trade(session, c["id"], -2_500.0)
    combine = session.get(Combine, c["id"])
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(session, combine)
    assert ei.value.status_code == 403
    assert "FAILED" in str(ei.value.detail)
    session.close()


def test_require_tradeable_blocks_day_locked_combine(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    session = session_factory()
    # -1_500 today = the 50K DLL budget → day-locked, but balance 48_500
    # stays above the 48_000 floor, so it's locked (not failed).
    _seed_closed_trade(session, c["id"], -1_500.0)
    combine = session.get(Combine, c["id"])
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(session, combine)
    assert ei.value.status_code == 403
    assert "Daily loss limit" in str(ei.value.detail)
    session.close()


def test_require_tradeable_allows_healthy_combine(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    session = session_factory()
    combine = session.get(Combine, c["id"])
    zerodte._require_tradeable(session, combine)  # must not raise
    session.close()
