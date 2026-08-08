"""Personal risk controls — DLL enforcement MODES + the daily profit target.

Feature 1 of the TopstepX-parity pass:
  * per-tier DLL overrides carry a mode: "alert" (event only), "liquidate"
    (flatten, keep trading), "liquidate_block" (flatten + day-lock — the
    historical behavior legacy bare-float overrides map to);
  * the FIRM tier-default DLL / MLL stay senior for alert/liquidate modes;
  * same-day tighten-only lock-in on liquidate_block overrides (409s);
  * per-user daily PROFIT target: lock=true → flatten + day-lock ("protect
    the green day"), lock=false → once-per-day event.

Monitor paths run through run_order_monitor with injected callables (no
network); trades are seeded straight into the DB.
"""

from __future__ import annotations

from datetime import datetime, time as dt_time, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import models.combine_event  # noqa: F401 — ensure combine_events table exists
from models.combine import Combine
from models.combine_event import CombineEvent
from models.trade import Trade
from models.user import User
from routers import zerodte
from services.combine_state import combine_snapshot
from services.order_monitor import run_order_monitor
from tests.conftest import make_combine

# "Today" is the EASTERN trading day (the monitor resolves the session in ET);
# a UTC date flips a day early after ~20:00 ET.
_TODAY_DATE = datetime.now(zerodte._ET).date()
_TODAY = _TODAY_DATE.isoformat()
# Mid-session ET so the seeded 0DTE legs are never treated as expired whatever
# wall-clock time the suite runs at (run_order_monitor's default `now` is the
# real time — past 16:00 ET it settles them instead of running the triggers).
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


def _seed_open_position(
    session_factory, combine_id: int, realized: float | None = None
) -> int:
    """A bracket-less OPEN position — only the liquidation pass can act on it.
    `realized` seeds a scale-out P&L already booked onto the still-open row."""
    s = session_factory()
    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        status="open",
        is_paper=True,
        notes="seed",
        tier="50K",
        combine_id=combine_id,
        realized_pnl=realized,
    )
    t.legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY, "contracts": 1, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _run(session_factory, **kw):
    params = dict(
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 1.0,
        unrealized_for=lambda t, s: 0.0,
        now=_NOON_ET,
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


def _events(session, combine_id: int, type_: str) -> list[CombineEvent]:
    return (
        session.execute(
            select(CombineEvent).where(
                CombineEvent.combine_id == combine_id, CombineEvent.type == type_
            )
        )
        .scalars()
        .all()
    )


def _put_overrides(client, body: dict):
    return client.put("/api/account/dll-overrides", json=body)


# --- alert mode ---------------------------------------------------------------


def test_alert_mode_records_event_but_does_not_flatten_or_lock(
    auth_client, session_factory
):
    c = make_combine(auth_client, "50K")
    res = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "alert"}}}
    )
    assert res.status_code == 200
    assert res.json()["overrides"]["50K"]["mode"] == "alert"

    tid = _seed_open_position(session_factory, c["id"])
    # -$900 open loss: over the $800 personal limit, under the $1,500 firm DLL.
    summary = _run(session_factory, unrealized_for=lambda t, s: -900.0)
    assert summary["liquidated"] == 0  # no flatten

    s = session_factory()
    assert s.get(Trade, tid).status == "open"  # position survives
    assert len(_events(s, c["id"], "personal_dll")) == 1
    combine = s.get(Combine, c["id"])
    snap = combine_snapshot(s, combine)
    assert snap.day_locked is False  # no lock — the FIRM budget is untouched
    assert snap.dll_budget == 1_500.0  # alert override never moves the gate
    zerodte._require_tradeable(s, combine)  # must not raise
    s.close()

    # Once per trading day: a second pass records no duplicate event.
    _run(session_factory, unrealized_for=lambda t, s: -900.0)
    s = session_factory()
    assert len(_events(s, c["id"], "personal_dll")) == 1
    s.close()


def test_alert_mode_counts_scaleout_loss_booked_on_open_row(
    auth_client, session_factory
):
    """A loss locked in by scaling out of a still-open position lives on the
    open row's realized_pnl — not in closed-trade realized nor in URPL. The
    personal DLL must still count it, else a trader scales 9/10 lots out at a
    loss, holds 1 near breakeven, and never trips their own limit."""
    c = make_combine(auth_client, "50K")
    _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "alert"}}}
    )
    # -$900 already booked via scale-out on the still-open row; URPL ~ 0.
    tid = _seed_open_position(session_factory, c["id"], realized=-900.0)
    summary = _run(session_factory, unrealized_for=lambda t, s: 0.0)
    assert summary["liquidated"] == 0  # alert never flattens

    s = session_factory()
    assert s.get(Trade, tid).status == "open"
    assert len(_events(s, c["id"], "personal_dll")) == 1  # limit tripped
    s.close()


# --- liquidate mode -------------------------------------------------------------


def test_liquidate_mode_flattens_but_reopen_stays_allowed(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "liquidate"}}}
    )

    tid = _seed_open_position(session_factory, c["id"])
    summary = _run(session_factory, unrealized_for=lambda t, s: -900.0)
    assert summary["liquidated"] == 1

    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed"
    assert t.close_reason == "liquidation"
    assert "personal daily loss limit" in (t.notes or "")
    combine = s.get(Combine, c["id"])
    assert combine.outcome == "active"  # not failed — MLL untouched
    snap = combine_snapshot(s, combine)
    assert snap.day_locked is False  # NO day-lock
    zerodte._require_tradeable(s, combine)  # re-open allowed — must not raise
    assert len(_events(s, c["id"], "liquidated")) == 1
    s.close()


# --- liquidate_block mode -------------------------------------------------------


def test_liquidate_block_mode_flattens_and_day_locks(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "liquidate_block"}}}
    )

    session = session_factory()
    # Realized day-loss already over the $800 personal blocking budget (but
    # under the firm $1,500 default — the override IS the budget in this mode).
    _seed_closed_trade(session, c["id"], -900.0)
    session.close()
    tid = _seed_open_position(session_factory, c["id"])

    summary = _run(session_factory, unrealized_for=lambda t, s: 50.0)
    assert summary["liquidated"] == 1  # day-lock flatten fired

    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed"
    assert t.close_reason == "liquidation"
    assert "day-locked" in (t.notes or "")
    combine = s.get(Combine, c["id"])
    snap = combine_snapshot(s, combine)
    assert snap.day_locked is True
    assert snap.dll_budget == 800.0
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(s, combine)
    assert ei.value.status_code == 403
    assert "Daily loss limit" in str(ei.value.detail)
    s.close()


# --- legacy bare-float compat ---------------------------------------------------


def test_legacy_bare_float_override_reads_and_behaves_as_liquidate_block(
    auth_client, session_factory
):
    c = make_combine(auth_client, "50K")
    # Write the LEGACY storage shape directly — a bare float in the JSON.
    s = session_factory()
    user = s.execute(select(User)).scalars().one()
    user.dll_overrides_json = '{"50K": 800.0}'
    s.add(user)
    s.commit()
    s.close()

    got = auth_client.get("/api/account/dll-overrides").json()
    assert got["overrides"]["50K"] == {
        "amount": 800.0, "mode": "liquidate_block", "set_at": None,
    }

    s = session_factory()
    _seed_closed_trade(s, c["id"], -900.0)  # over 800, under the 1,500 default
    combine = s.get(Combine, c["id"])
    snap = combine_snapshot(s, combine)
    assert snap.day_locked is True  # legacy float = blocking budget, as before
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(s, combine)
    assert ei.value.status_code == 403
    s.close()


# --- same-day tighten-only lock-in ----------------------------------------------


def test_same_day_weaken_raise_or_remove_rejected(auth_client):
    r = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "liquidate_block"}}}
    )
    assert r.status_code == 200

    # RAISE → 409
    r = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 1000, "mode": "liquidate_block"}}}
    )
    assert r.status_code == 409

    # WEAKEN the mode → 409
    r = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "alert"}}}
    )
    assert r.status_code == 409
    r = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "liquidate"}}}
    )
    assert r.status_code == 409

    # REMOVE → 409
    r = _put_overrides(auth_client, {"overrides": {}})
    assert r.status_code == 409

    # Switching the DLL OFF for the locked tier → 409
    r = _put_overrides(
        auth_client, {"overrides": {"50K": 800}, "disabled": ["50K"]}
    )
    assert r.status_code == 409

    # TIGHTEN (lower) → allowed, and re-locks at the new level
    r = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 600, "mode": "liquidate_block"}}}
    )
    assert r.status_code == 200
    assert r.json()["overrides"]["50K"]["amount"] == 600

    # Raising back (bare number maps to liquidate_block) → 409 again
    r = _put_overrides(auth_client, {"overrides": {"50K": 800}})
    assert r.status_code == 409


def test_non_blocking_modes_stay_freely_editable(auth_client):
    """alert/liquidate overrides never lock in — only liquidate_block does."""
    r = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "alert"}}}
    )
    assert r.status_code == 200
    # Raise it, weaken it, remove it — all fine same-day.
    r = _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 2000, "mode": "alert"}}}
    )
    assert r.status_code == 200
    r = _put_overrides(auth_client, {"overrides": {}})
    assert r.status_code == 200


# --- personal daily profit target -----------------------------------------------


def test_profit_target_round_trip_and_clear(auth_client):
    # Unset by default.
    assert auth_client.get("/api/account/dll-overrides").json()["profit_target"] is None

    r = _put_overrides(
        auth_client,
        {"overrides": {}, "profit_target": {"amount": 500, "lock": True}},
    )
    assert r.status_code == 200
    assert r.json()["profit_target"] == {"amount": 500.0, "lock": True}

    # PUT WITHOUT the key leaves it untouched.
    r = _put_overrides(auth_client, {"overrides": {}})
    assert r.status_code == 200
    assert r.json()["profit_target"] == {"amount": 500.0, "lock": True}

    # Explicit null clears it.
    r = _put_overrides(auth_client, {"overrides": {}, "profit_target": None})
    assert r.status_code == 200
    assert r.json()["profit_target"] is None


def test_profit_target_lock_flattens_and_day_locks_on_plus_amount(
    auth_client, session_factory
):
    c = make_combine(auth_client, "50K")
    _put_overrides(
        auth_client,
        {"overrides": {}, "profit_target": {"amount": 500, "lock": True}},
    )
    tid = _seed_open_position(session_factory, c["id"])

    # +$600 open URPL: day P&L (realized 0 + URPL) crosses the +$500 target.
    summary = _run(session_factory, unrealized_for=lambda t, s: 600.0)
    assert summary["liquidated"] == 1

    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed"
    assert t.close_reason == "liquidation"
    assert "profit target" in (t.notes or "")
    combine = s.get(Combine, c["id"])
    assert combine.profit_locked_at is not None
    snap = combine_snapshot(s, combine)
    assert snap.day_locked is True
    assert snap.profit_locked is True
    assert combine.outcome == "active"  # a green day never fails the combine
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(s, combine)
    assert ei.value.status_code == 403
    assert "Profit target" in str(ei.value.detail)
    events = _events(s, c["id"], "profit_target")
    assert len(events) == 1
    assert "day protected" in events[0].message
    s.close()


def test_profit_target_without_lock_records_event_only(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _put_overrides(
        auth_client,
        {"overrides": {}, "profit_target": {"amount": 500, "lock": False}},
    )
    tid = _seed_open_position(session_factory, c["id"])

    summary = _run(session_factory, unrealized_for=lambda t, s: 600.0)
    assert summary["liquidated"] == 0

    s = session_factory()
    assert s.get(Trade, tid).status == "open"  # nothing closed
    combine = s.get(Combine, c["id"])
    assert combine.profit_locked_at is None
    snap = combine_snapshot(s, combine)
    assert snap.day_locked is False
    assert len(_events(s, c["id"], "profit_target")) == 1
    s.close()

    # Once per trading day.
    _run(session_factory, unrealized_for=lambda t, s: 600.0)
    s = session_factory()
    assert len(_events(s, c["id"], "profit_target")) == 1
    s.close()


def test_profit_target_lock_engages_on_realized_basis_without_open_book(
    auth_client, session_factory
):
    """A green day banked by manual closes (no open book for the monitor to
    flatten) still day-protects on the next snapshot read."""
    c = make_combine(auth_client, "50K")
    _put_overrides(
        auth_client,
        {"overrides": {}, "profit_target": {"amount": 500, "lock": True}},
    )
    s = session_factory()
    _seed_closed_trade(s, c["id"], 600.0)  # +600 realized today, book flat
    combine = s.get(Combine, c["id"])
    snap = combine_snapshot(s, combine)
    assert snap.profit_locked is True
    assert snap.day_locked is True
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(s, combine)
    assert ei.value.status_code == 403
    assert "Profit target" in str(ei.value.detail)
    assert len(_events(s, c["id"], "profit_target")) == 1
    s.close()


def test_firm_dll_stays_senior_over_alert_override(auth_client, session_factory):
    """With an alert-mode override, hitting the FIRM tier default still
    day-lock-flattens exactly as before — the mode only affects the personal
    trigger, never the firm rule."""
    c = make_combine(auth_client, "50K")
    _put_overrides(
        auth_client, {"overrides": {"50K": {"amount": 800, "mode": "alert"}}}
    )
    session = session_factory()
    # Realized day-loss AT the firm $1,500 budget → firm day-lock engages.
    _seed_closed_trade(session, c["id"], -1_500.0)
    session.close()
    tid = _seed_open_position(session_factory, c["id"])

    # The open position is a small LOSER so the flatten keeps the realized
    # day-loss at/over the firm budget (day_locked derives from realized).
    summary = _run(session_factory, unrealized_for=lambda t, s: -100.0)
    assert summary["liquidated"] == 1  # firm day-lock flatten, mode irrelevant

    s = session_factory()
    assert s.get(Trade, tid).status == "closed"
    combine = s.get(Combine, c["id"])
    with pytest.raises(HTTPException) as ei:
        zerodte._require_tradeable(s, combine)
    assert ei.value.status_code == 403
    assert "Daily loss limit" in str(ei.value.detail)
    s.close()
