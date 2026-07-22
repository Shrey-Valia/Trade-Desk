"""Fill-time quote gate — a working SELL entry may not book credit off a
model mark. It rests through cold ticks (skip, never cancel) and fills the
moment a genuine two-sided market exists. Buys keep the mid fallback.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime
from datetime import time as dt_time

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from config import settings
from models.trade import Trade
from services.order_monitor import run_order_monitor
from tests.conftest import make_combine

_TODAY = datetime.now(UTC).date()


def _seed_working(session_factory, combine_id, action, order_type="stop",
                  trigger=2.0, legs=None):
    s = session_factory()
    t = Trade(
        symbol="SPY", strategy=f"{'short' if action == 'sell' else 'long'}_call",
        entry_date=datetime.now(UTC), entry_underlying_price=100.0,
        net_debit_credit=0.0, is_paper=True, tier="50K",
        combine_id=combine_id, status="working",
        order_type=order_type, limit_price=trigger,
    )
    t.legs = legs or [
        {"side": "call", "action": action, "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 3.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _run(session_factory, mark):
    return run_order_monitor(
        session_factory=session_factory,
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: mark,
        unrealized_for=lambda t, s: 0.0,
        now=datetime.combine(_TODAY, dt_time(17, 0), tzinfo=UTC),
    )


def _get(session_factory, tid):
    s = session_factory()
    t = s.get(Trade, tid)
    s.close()
    return t


def _quote(bid=None, ask=None):
    return types.SimpleNamespace(bid=bid, ask=ask, last=None)


def _pin_quotes(monkeypatch, q):
    monkeypatch.setattr(
        "services.fills.live_leg_quotes",
        lambda sym, legs: {(leg["strike"], leg["side"]): q for leg in legs}
        if q is not None
        else {},
    )


def test_triggered_sell_rests_through_a_cold_feed(auth_client, session_factory, monkeypatch):
    """The exploit path: premium decays past the sell-stop but NO live market
    exists — before the gate this booked fabricated credit off the model
    mark. Now it stays working."""
    c = make_combine(auth_client, "50K")
    tid = _seed_working(session_factory, c["id"], "sell")
    _pin_quotes(monkeypatch, None)  # cold feed
    summary = _run(session_factory, mark=-1.8)  # per-share 1.8 ≤ stop 2.0
    assert summary["filled"] == 0
    assert _get(session_factory, tid).status == "working"  # skipped, NOT cancelled


def test_sell_fills_once_a_two_sided_market_exists(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed_working(session_factory, c["id"], "sell")
    _pin_quotes(monkeypatch, _quote(bid=1.7, ask=1.9))
    summary = _run(session_factory, mark=-1.8)
    assert summary["filled"] == 1
    t = _get(session_factory, tid)
    assert t.status == "open"
    assert t.legs[0]["entry_price"] > 1.0  # real bid-side credit, never $0.01


def test_one_sided_quote_is_not_a_market_for_a_sell(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed_working(session_factory, c["id"], "sell")
    _pin_quotes(monkeypatch, _quote(bid=None, ask=1.9))
    assert _run(session_factory, mark=-1.8)["filled"] == 0
    assert _get(session_factory, tid).status == "working"


def test_buy_keeps_the_mid_fallback(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed_working(
        session_factory, c["id"], "buy", order_type="limit", trigger=2.0
    )
    _pin_quotes(monkeypatch, None)  # cold feed — buys still fill at the mid
    summary = _run(session_factory, mark=1.8)  # 1.8 ≤ limit 2.0
    assert summary["filled"] == 1
    assert _get(session_factory, tid).status == "open"


def test_multi_leg_net_fill_gated_on_its_sell_legs(auth_client, session_factory, monkeypatch):
    """A credit spread's net-limit fill needs the SHORT leg quoted two-sided;
    the long wing alone doesn't unblock it."""
    c = make_combine(auth_client, "50K")
    legs = [
        {"side": "put", "action": "sell", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0},
        {"side": "put", "action": "buy", "strike": 95.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 0.4},
    ]
    tid = _seed_working(
        session_factory, c["id"], "sell", order_type="limit",
        trigger=-0.5, legs=legs,
    )
    _pin_quotes(monkeypatch, None)
    # Net mark −0.6 ≤ signed limit −0.5 → triggered, but cold feed → rests.
    assert _run(session_factory, mark=-0.6)["filled"] == 0
    assert _get(session_factory, tid).status == "working"
    _pin_quotes(monkeypatch, _quote(bid=0.5, ask=0.7))
    assert _run(session_factory, mark=-0.6)["filled"] == 1


def test_gate_off_restores_legacy_mid_fills(auth_client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "working_sell_fill_requires_quote", False)
    c = make_combine(auth_client, "50K")
    tid = _seed_working(session_factory, c["id"], "sell")
    _pin_quotes(monkeypatch, None)
    assert _run(session_factory, mark=-1.8)["filled"] == 1
    assert _get(session_factory, tid).status == "open"
