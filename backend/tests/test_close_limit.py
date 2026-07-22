"""Resting close-limit orders — trigger semantics, monitor fills, API.

The close-limit is the missing half of the order lifecycle: every close was
market-at-mark before it. Convention under test: close_limit_price is the
SIGNED net premium per 1x structure (debit positive / credit negative), one
uniform trigger net_1x >= limit, booked AT the limit with no spread friction
and commission on both sides.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime
from datetime import time as dt_time

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from config import settings
from models.trade import Trade
from services.order_monitor import _close_limit_triggered, run_order_monitor
from tests.conftest import make_combine

_TODAY = datetime.now(UTC).date()
_FEE = settings.per_contract_fee


def _seed(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(UTC),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
        status="open",
    )
    defaults.update(kw)
    legs = defaults.pop("_legs", None)
    t = Trade(**defaults)
    t.legs = legs or [
        {
            "side": "call",
            "action": "buy",
            "strike": 100.0,
            "expiry": _TODAY.isoformat(),
            "contracts": 1,
            "entry_price": 1.0,
        }
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
        # Mid-session on the seeded legs' expiry date — see test_order_monitor.
        now=datetime.combine(_TODAY, dt_time(17, 0), tzinfo=UTC),
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


def _get(session_factory, tid):
    s = session_factory()
    t = s.get(Trade, tid)
    s.close()
    return t


# --- pure trigger logic -----------------------------------------------------


def _mk(legs, close_limit):
    t = Trade(
        symbol="SPY", strategy="custom", entry_date=datetime.now(UTC),
        entry_underlying_price=100.0, net_debit_credit=0.0,
        close_limit_price=close_limit,
    )
    t.legs = legs
    return t


def test_trigger_long_fires_at_or_above_limit():
    t = _mk([{"action": "buy", "contracts": 1, "entry_price": 1.0}], 1.5)
    assert not _close_limit_triggered(t, 1.4)
    assert _close_limit_triggered(t, 1.5)
    assert _close_limit_triggered(t, 1.8)


def test_trigger_short_fires_when_buyback_cheap_enough():
    # Short at 1.00, buy back at <= 0.30 → limit -0.30; net mark is negative
    # and RISES toward zero as the premium decays.
    t = _mk([{"action": "sell", "contracts": 1, "entry_price": 1.0}], -0.30)
    assert not _close_limit_triggered(t, -0.40)  # still costs 0.40 to close
    assert _close_limit_triggered(t, -0.30)
    assert _close_limit_triggered(t, -0.10)


def test_trigger_scales_by_structure_base():
    # 2x vertical: net mark is contracts-scaled; the limit is per 1x.
    legs = [
        {"action": "buy", "contracts": 2, "entry_price": 1.0},
        {"action": "sell", "contracts": 2, "entry_price": 0.5},
    ]
    t = _mk(legs, 0.8)
    assert not _close_limit_triggered(t, 1.5)   # net_1x 0.75 < 0.8
    assert _close_limit_triggered(t, 1.7)       # net_1x 0.85 >= 0.8


# --- monitor fills ----------------------------------------------------------


def test_close_limit_long_books_at_limit(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], close_limit_price=1.5)
    summary = _run(session_factory, option_mark=lambda t, s: 1.6)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.status == "closed"
    assert t.close_reason == "limit"
    # Booked AT the limit, no spread friction, commission both sides:
    # (1.5 − 1.0) × 100 − 2×fee.
    assert t.realized_pnl == round(50.0 - 2 * _FEE, 2)


def test_close_limit_not_triggered_stays_open(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], close_limit_price=1.5)
    summary = _run(session_factory, option_mark=lambda t, s: 1.4)
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


def test_close_limit_short_buyback(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    legs = [{"side": "call", "action": "sell", "strike": 100.0,
             "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}]
    tid = _seed(
        session_factory, c["id"], strategy="short_call",
        _legs=legs, close_limit_price=-0.30,
    )
    # Premium decayed to 0.25 → net mark -0.25 >= -0.30 → buy back at 0.30.
    summary = _run(session_factory, option_mark=lambda t, s: -0.25)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.close_reason == "limit"
    # (-0.30 − (−1.00)) × 100 − 2×fee = 70 − 2×fee.
    assert t.realized_pnl == round(70.0 - 2 * _FEE, 2)


def test_close_limit_short_not_there_yet(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    legs = [{"side": "call", "action": "sell", "strike": 100.0,
             "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}]
    tid = _seed(
        session_factory, c["id"], strategy="short_call",
        _legs=legs, close_limit_price=-0.30,
    )
    summary = _run(session_factory, option_mark=lambda t, s: -0.40)
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


def test_close_limit_multi_leg_per_1x(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 2, "entry_price": 1.0},
        {"side": "call", "action": "sell", "strike": 105.0,
         "expiry": _TODAY.isoformat(), "contracts": 2, "entry_price": 0.5},
    ]
    tid = _seed(
        session_factory, c["id"], strategy="bull_call_spread",
        _legs=legs, close_limit_price=0.8,
    )
    summary = _run(session_factory, option_mark=lambda t, s: 1.7)  # net_1x 0.85
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.close_reason == "limit"
    # (0.8 × base 2 − entry_net 1.0) × 100 − round-trip commission on 4
    # total contracts: 60 − 8×fee.
    assert t.realized_pnl == round(60.0 - 8 * _FEE, 2)


def test_close_limit_alone_is_monitored(auth_client, session_factory):
    """The run-loop skip guard must NOT skip an open position whose only
    exit is the resting close-limit (no brackets, no trailing, no premium)."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], close_limit_price=1.2)
    summary = _run(session_factory, option_mark=lambda t, s: 1.3)
    assert summary["closed"] == 1
    assert _get(session_factory, tid).close_reason == "limit"


def test_close_limit_wins_over_premium_tp_same_tick(auth_client, session_factory):
    """When the trader's named limit and a premium-multiple TP would both
    fire on one tick, the named price wins (and books at it exactly)."""
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], close_limit_price=1.5, tp_premium_mult=1.2,
    )
    summary = _run(session_factory, option_mark=lambda t, s: 1.6)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.close_reason == "limit"
    assert t.realized_pnl == round(50.0 - 2 * _FEE, 2)


def test_close_limit_idempotent_second_pass(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _seed(session_factory, c["id"], close_limit_price=1.5)
    _run(session_factory, option_mark=lambda t, s: 1.6)
    summary = _run(session_factory, option_mark=lambda t, s: 1.6)
    assert summary["closed"] == 0


# --- API --------------------------------------------------------------------


def _pin_mark(monkeypatch, price=100.0, mark=1.0):
    """Pin the marketability guard's inputs (the suite may run with live API
    keys, in which case get_quotes returns the real SPY print)."""
    monkeypatch.setattr(
        "routers.journal.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=price)},
    )
    monkeypatch.setattr(
        "services.order_monitor._default_option_mark", lambda t, s, now: mark
    )


def test_set_close_order_on_open_position(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    _pin_mark(monkeypatch)  # mark 1.0 < limit 1.5 → non-marketable, accepted
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-order", json={"limit_price": 1.5}
    )
    assert res.status_code == 200, res.text
    assert res.json()["close_limit_price"] == 1.5


def test_set_close_order_replaces_prior(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], close_limit_price=1.5)
    _pin_mark(monkeypatch)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-order", json={"limit_price": 2.0}
    )
    assert res.status_code == 200
    assert res.json()["close_limit_price"] == 2.0


def test_close_order_sign_must_match_direction(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])  # net-debit long
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-order", json={"limit_price": -0.5}
    )
    assert res.status_code == 422

    legs = [{"side": "call", "action": "sell", "strike": 100.0,
             "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}]
    tid2 = _seed(session_factory, c["id"], strategy="short_call", _legs=legs)
    res = auth_client.post(
        f"/api/journal/trades/{tid2}/close-order", json={"limit_price": 0.5}
    )
    assert res.status_code == 422


def test_close_order_rejected_when_not_open(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"],
        status="working", order_type="limit", limit_price=1.0,
    )
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-order", json={"limit_price": 1.5}
    )
    assert res.status_code == 409
    tid2 = _seed(session_factory, c["id"], status="closed")
    res = auth_client.delete(f"/api/journal/trades/{tid2}/close-order")
    assert res.status_code == 409


def test_close_order_marketable_limit_rejected(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    monkeypatch.setattr(
        "routers.journal.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )
    # Live net mark 1.6 >= requested limit 1.5 → immediately fillable → 422.
    monkeypatch.setattr(
        "services.order_monitor._default_option_mark", lambda t, s, now: 1.6
    )
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-order", json={"limit_price": 1.5}
    )
    assert res.status_code == 422
    assert "marketable" in res.json()["detail"]


def test_clear_close_order(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], close_limit_price=1.5)
    res = auth_client.delete(f"/api/journal/trades/{tid}/close-order")
    assert res.status_code == 200
    assert res.json()["close_limit_price"] is None
    assert _get(session_factory, tid).close_limit_price is None
