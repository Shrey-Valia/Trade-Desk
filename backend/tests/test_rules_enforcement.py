"""Rule enforcement on the trade-open path + the scheduled settlement job.

Covers the two halves of "make the rules real": _require_tradeable() (the
server-side open gate) and settle_combines() (the clock-driven auto-fail /
settlement that no longer waits for a read)."""

from __future__ import annotations

from datetime import datetime, time as dt_time, timezone

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

# EASTERN trading day + a mid-session ET clock: the auto-liquidation tests seed
# 0DTE positions and drive the monitor, so `now` must be mid-session on the
# seeded expiry — the default (real time) settles the legs as expired past
# 16:00 ET and the liquidation path under test never runs.
_TODAY_DATE = datetime.now(zerodte._ET).date()
_NOON_ET = datetime.combine(_TODAY_DATE, dt_time(12, 0), tzinfo=zerodte._ET)


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


def test_require_tradeable_enforces_custom_dll_override(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    # Tighten the 50K DLL from its $1,500 default to $800.
    res = auth_client.put(
        "/api/account/dll-overrides", json={"overrides": {"50K": 800}}
    )
    assert res.status_code == 200
    assert res.json()["overrides"]["50K"]["amount"] == 800
    # A legacy bare-number PUT maps to liquidate_block (today's behavior).
    assert res.json()["overrides"]["50K"]["mode"] == "liquidate_block"

    session = session_factory()
    # -$1,000 today: under the $1,500 default but OVER the $800 override.
    _seed_closed_trade(session, c["id"], -1_000.0)
    combine = session.get(Combine, c["id"])
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(session, combine)
    assert ei.value.status_code == 403
    assert "Daily loss limit" in str(ei.value.detail)
    session.close()


def test_dll_override_clamped_to_band(auth_client):
    # 50K band = 1-10% of $50,000 = $500-$5,000. $50 clamps up to $500.
    res = auth_client.put("/api/account/dll-overrides", json={"overrides": {"50K": 50}})
    assert res.status_code == 200
    assert res.json()["overrides"]["50K"]["amount"] == 500
    got = auth_client.get("/api/account/dll-overrides").json()
    assert got["overrides"]["50K"]["amount"] == 500


def test_dll_override_rejects_unknown_tier(auth_client):
    res = auth_client.put(
        "/api/account/dll-overrides", json={"overrides": {"999K": 1000}}
    )
    assert res.status_code == 422


# --- DLL-off toggle ---------------------------------------------------------


def test_dll_disable_round_trips(auth_client):
    """Setting the disable list persists and reads back; an amount-only edit
    (disabled omitted) leaves it untouched."""
    res = auth_client.put(
        "/api/account/dll-overrides", json={"overrides": {}, "disabled": ["50K"]}
    )
    assert res.status_code == 200
    assert res.json()["disabled"] == ["50K"]
    assert auth_client.get("/api/account/dll-overrides").json()["disabled"] == ["50K"]

    # Amount-only edit (no `disabled` key) must NOT clear the disable set.
    res = auth_client.put("/api/account/dll-overrides", json={"overrides": {"100K": 2000}})
    assert res.status_code == 200
    assert res.json()["disabled"] == ["50K"]


def test_dll_disable_rejects_unknown_tier(auth_client):
    res = auth_client.put(
        "/api/account/dll-overrides", json={"overrides": {}, "disabled": ["999K"]}
    )
    assert res.status_code == 422


def test_dll_off_does_not_day_lock_require_tradeable(auth_client, session_factory):
    """With the 50K DLL switched OFF, a today-loss that would normally hit the
    DLL no longer day-locks — _require_tradeable allows the open (MLL still
    above its floor)."""
    c = make_combine(auth_client, "50K")
    res = auth_client.put(
        "/api/account/dll-overrides", json={"overrides": {}, "disabled": ["50K"]}
    )
    assert res.status_code == 200

    session = session_factory()
    # -1,500 today = the 50K DLL budget → would day-lock if the DLL were on,
    # but balance 48,500 stays above the 48,000 MLL floor.
    _seed_closed_trade(session, c["id"], -1_500.0)
    combine = session.get(Combine, c["id"])
    zerodte._require_tradeable(session, combine)  # must NOT raise (DLL off)
    session.close()


def test_dll_off_still_fails_on_mll_breach(auth_client, session_factory):
    """The DLL-off toggle must NOT relax the MLL floor — a realized MLL breach
    still blocks _require_tradeable with the DLL disabled."""
    c = make_combine(auth_client, "50K")
    auth_client.put(
        "/api/account/dll-overrides", json={"overrides": {}, "disabled": ["50K"]}
    )
    session = session_factory()
    _seed_closed_trade(session, c["id"], -2_500.0)  # 47,500 ≤ 48,000 floor
    combine = session.get(Combine, c["id"])
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(session, combine)
    assert ei.value.status_code == 403
    assert "FAILED" in str(ei.value.detail)
    session.close()


def test_dll_off_skips_dll_liquidation(auth_client, session_factory):
    """With the DLL off, a pure DLL breach (open loss exhausts the budget while
    the MLL floor is clear) does NOT auto-liquidate — the DLL branch is
    skipped. The MLL path is unaffected."""
    from services.order_monitor import run_order_monitor

    c = make_combine(auth_client, "50K")
    auth_client.put(
        "/api/account/dll-overrides", json={"overrides": {}, "disabled": ["50K"]}
    )
    session = session_factory()
    tid = _seed_open_position(session, c["id"])

    # -1,500 open loss = the DLL budget, but balance 48,500 > 48,000 MLL floor.
    # With the DLL on this liquidates (DLL path); with it OFF nothing closes.
    summary = run_order_monitor(
        session_factory=session_factory,
        market_open=lambda: True,
        spot_for=lambda sym: 99.0,
        unrealized_for=lambda t, s: -1_500.0,
        now=_NOON_ET,
    )
    assert summary["liquidated"] == 0
    session = session_factory()
    assert session.get(Trade, tid).status == "open"
    assert session.get(Combine, c["id"]).outcome == "active"
    session.close()


# --- hard auto-liquidation (order monitor) ----------------------------------


def _seed_open_position(session, combine_id: int) -> int:
    """A bracket-less OPEN position — only the liquidation pass can act on it."""
    now = datetime.now(timezone.utc)
    today = _TODAY_DATE.isoformat()  # ET session day — matches _NOON_ET
    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=now,
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        status="open",
        is_paper=True,
        notes="seed",
        tier="50K",
        combine_id=combine_id,
    )
    t.legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": today, "contracts": 1, "entry_price": 1.0}
    ]
    session.add(t)
    session.commit()
    tid = t.id
    session.close()
    return tid


def test_auto_liquidation_force_closes_and_fails_on_mll_breach(auth_client, session_factory):
    """The headline: a live-balance MLL breach (driven by open-position URPL)
    force-closes every open position on the combine and marks it FAILED."""
    from services.order_monitor import run_order_monitor

    c = make_combine(auth_client, "50K")
    session = session_factory()
    tid = _seed_open_position(session, c["id"])

    # 50K floor = 48,000. Realized balance is 50,000; a −2,600 open URPL drops
    # the LIVE balance to 47,400 ≤ 48,000 → breach.
    summary = run_order_monitor(
        session_factory=session_factory,
        market_open=lambda: True,
        spot_for=lambda sym: 99.0,
        unrealized_for=lambda t, s: -2_600.0,
        now=_NOON_ET,
    )
    assert summary["liquidated"] == 1

    session = session_factory()
    trade = session.get(Trade, tid)
    assert trade.status == "closed"
    assert trade.close_reason == "liquidation"
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


def test_auto_liquidation_leaves_healthy_combine_open(auth_client, session_factory):
    """A small open loss that stays above MLL and under DLL → nothing closes."""
    from services.order_monitor import run_order_monitor

    c = make_combine(auth_client, "50K")
    session = session_factory()
    tid = _seed_open_position(session, c["id"])

    summary = run_order_monitor(
        session_factory=session_factory,
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        unrealized_for=lambda t, s: -200.0,
        now=_NOON_ET,
    )
    assert summary["liquidated"] == 0

    session = session_factory()
    assert session.get(Trade, tid).status == "open"
    assert session.get(Combine, c["id"]).outcome == "active"
    session.close()
