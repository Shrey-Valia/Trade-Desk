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
