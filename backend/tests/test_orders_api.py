"""Order placement (limit/stop → working), brackets PUT, and cancel API."""

from __future__ import annotations

import types
from datetime import datetime, timezone

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from models.trade import Trade
from routers import zerodte
from tests.conftest import make_combine

_TODAY = datetime.now(zerodte._ET).date()


def _stub_market(monkeypatch):
    """Make the 0DTE open path think the session is open with a live SPY."""
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot",
        lambda sym, with_volume=False: [types.SimpleNamespace(expiry=_TODAY)],
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


def _seed_trade(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
        status="open",
    )
    defaults.update(kw)
    t = Trade(**defaults)
    t.legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


# --- placement --------------------------------------------------------------


def test_limit_order_creates_working_trade(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={
            "symbol": "SPY", "side": "call", "action": "buy", "strike": 100,
            "entry_price": 0, "order_type": "limit", "limit_price": 0.50,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "working"
    assert body["order_type"] == "limit"
    assert body["limit_price"] == 0.50


def test_market_order_still_opens_immediately(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={"symbol": "SPY", "side": "call", "action": "buy", "strike": 100, "entry_price": 1.25},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "open"
    assert body["order_type"] == "market"


def test_limit_order_with_brackets(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={
            "symbol": "SPY", "side": "call", "action": "buy", "strike": 100,
            "entry_price": 0, "order_type": "limit", "limit_price": 0.50,
            "stop_loss": 95.0, "take_profit": 106.0,
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["stop_loss"] == 95.0 and body["take_profit"] == 106.0


def test_bracket_too_close_rejected(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={
            "symbol": "SPY", "side": "call", "action": "buy", "strike": 100,
            "entry_price": 1.0, "stop_loss": 100.02,  # < 0.1% of 100
        },
    )
    assert res.status_code == 422


# --- brackets PUT -----------------------------------------------------------


def test_set_and_clear_brackets(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed_trade(session_factory, c["id"])
    # set
    res = auth_client.put(f"/api/journal/trades/{tid}/brackets", json={"stop_loss": 95, "take_profit": 105})
    assert res.status_code == 200, res.text
    assert res.json()["stop_loss"] == 95 and res.json()["take_profit"] == 105
    # clear TP only (PUT semantics: omitted side clears)
    res = auth_client.put(f"/api/journal/trades/{tid}/brackets", json={"stop_loss": 95})
    assert res.json()["take_profit"] is None and res.json()["stop_loss"] == 95


def test_brackets_min_distance_422(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed_trade(session_factory, c["id"])  # entry_underlying_price 100
    # Pin the live spot so the min-distance guard is deterministic.
    monkeypatch.setattr(
        "routers.journal.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )
    res = auth_client.put(f"/api/journal/trades/{tid}/brackets", json={"stop_loss": 100.01})
    assert res.status_code == 422


def test_brackets_rejected_on_closed_trade(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed_trade(session_factory, c["id"], status="closed")
    res = auth_client.put(f"/api/journal/trades/{tid}/brackets", json={"stop_loss": 95})
    assert res.status_code == 409


# --- cancel -----------------------------------------------------------------


def test_cancel_working_order(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed_trade(session_factory, c["id"], status="working", order_type="limit", limit_price=1.0)
    res = auth_client.post(f"/api/journal/trades/{tid}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"


def test_cancel_rejected_when_not_working(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed_trade(session_factory, c["id"], status="open")
    res = auth_client.post(f"/api/journal/trades/{tid}/cancel")
    assert res.status_code == 409


# --- flatten / reverse-all --------------------------------------------------


def _stub_quote(monkeypatch, price=100.0):
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=price)},
    )


def test_flatten_closes_all_open_positions(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    a = _seed_trade(session_factory, c["id"], status="open")
    b = _seed_trade(session_factory, c["id"], status="open")
    _stub_quote(monkeypatch)

    res = auth_client.post("/api/zerodte/flatten")
    assert res.status_code == 200, res.text
    body = res.json()
    assert sorted(body["closed"]) == sorted([a, b])
    assert body["opened"] == []

    s = session_factory()
    assert s.get(Trade, a).status == "closed"
    assert s.get(Trade, b).status == "closed"
    # Each closed position booked a realized number (manual close reason).
    assert s.get(Trade, a).close_reason == "manual"
    assert s.get(Trade, a).realized_pnl is not None
    s.close()


def test_flatten_is_noop_with_nothing_open(auth_client, session_factory, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_quote(monkeypatch)
    res = auth_client.post("/api/zerodte/flatten")
    assert res.status_code == 200
    body = res.json()
    assert body["closed"] == [] and body["realized"] == 0.0


def test_flatten_leaves_working_orders_alone(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    open_t = _seed_trade(session_factory, c["id"], status="open")
    working = _seed_trade(
        session_factory, c["id"], status="working", order_type="limit", limit_price=1.0
    )
    _stub_quote(monkeypatch)
    res = auth_client.post("/api/zerodte/flatten")
    assert res.status_code == 200
    assert res.json()["closed"] == [open_t]
    s = session_factory()
    assert s.get(Trade, working).status == "working"  # untouched
    s.close()


def test_reverse_closes_and_opens_opposite_side(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    long_call = _seed_trade(
        session_factory, c["id"], status="open", strategy="long_call"
    )
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    _stub_quote(monkeypatch)

    res = auth_client.post("/api/zerodte/reverse")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["closed"] == [long_call]
    assert len(body["opened"]) == 1

    s = session_factory()
    assert s.get(Trade, long_call).status == "closed"
    rev = s.get(Trade, body["opened"][0])
    assert rev.status == "open"
    assert rev.strategy == "short_call"          # long → short
    assert rev.legs[0]["action"] == "sell"       # buy → sell
    assert "reversed from" in (rev.notes or "")
    s.close()


def test_reverse_rejected_when_market_closed(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    _seed_trade(session_factory, c["id"], status="open")
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: False)
    _stub_quote(monkeypatch)
    res = auth_client.post("/api/zerodte/reverse")
    assert res.status_code == 409


# --- deterministic fill slippage --------------------------------------------


def _q(bid=None, ask=None, last=None):
    return zerodte._LegQuote(symbol="X", strike=100.0, side="call", bid=bid, ask=ask, last=last)


def test_slippage_buyer_pays_above_mid_seller_receives_below():
    q = _q(bid=1.0, ask=1.2)  # mid 1.1, half-spread 0.1
    buy = zerodte._pick_fill_price(q, "buy", 1)
    sell = zerodte._pick_fill_price(q, "sell", 1)
    assert buy == 1.2   # mid 1.1 + half-spread 0.1
    assert sell == 1.0  # mid 1.1 − half-spread 0.1
    assert buy > 1.1 > sell  # never the perfect mid


def test_slippage_scales_with_size():
    q = _q(bid=1.0, ask=1.2)  # mid 1.1
    one = zerodte._pick_fill_price(q, "buy", 1)
    three = zerodte._pick_fill_price(q, "buy", 3)
    # 3 contracts: extra=2 → size_frac 0.01 → slip 0.1 + 1.1*0.01 = 0.111.
    assert three == 1.211
    assert three > one  # bigger clip → worse fill


def test_slippage_size_impact_is_capped():
    q = _q(bid=1.0, ask=1.2)  # mid 1.1
    huge = zerodte._pick_fill_price(q, "buy", 100)
    # size_frac caps at 0.05 → slip 0.1 + 1.1*0.05 = 0.155 → 1.255.
    assert huge == 1.255


def test_slippage_is_deterministic():
    q = _q(bid=1.0, ask=1.2)
    a = zerodte._pick_fill_price(q, "buy", 5)
    b = zerodte._pick_fill_price(q, "buy", 5)
    assert a == b  # no RNG


def test_slippage_last_only_synthesizes_a_touch_spread():
    q = _q(last=2.0)  # one-sided: 2% synthetic spread → half 0.02
    buy = zerodte._pick_fill_price(q, "buy", 1)
    assert buy == 2.02  # 2.0 + 0.02
    assert buy > 2.0    # still worse than the last/mid


def test_slippage_floor_keeps_price_positive():
    q = _q(bid=0.01, ask=0.05)  # mid 0.03, half-spread 0.02
    sell = zerodte._pick_fill_price(q, "sell", 50)  # large adverse size impact
    assert sell >= 0.01  # floored, never ≤ 0


def test_no_quote_returns_zero():
    assert zerodte._pick_fill_price(_q(), "buy", 1) == 0.0
