"""Roll ticket — atomic close + reopen at shifted strikes (/api/zerodte/roll).

A refused roll must leave the position untouched: strikes/margin/gates are
validated BEFORE the close books.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from config import settings
from models.trade import Trade
from routers import zerodte
from tests.conftest import make_combine

_TODAY = datetime.now(zerodte._ET).date()


def _leg(side, action, strike, price, contracts=1):
    return {
        "side": side, "action": action, "strike": strike,
        "expiry": _TODAY.isoformat(), "contracts": contracts,
        "entry_price": price,
    }


def _seed(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(UTC),
        entry_underlying_price=100.0,
        net_debit_credit=1.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
        status="open",
    )
    defaults.update(kw)
    legs = defaults.pop("_legs", None)
    t = Trade(**defaults)
    t.legs = legs or [_leg("call", "buy", 100.0, 1.0)]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _get(session_factory, tid):
    s = session_factory()
    t = s.get(Trade, tid)
    s.close()
    return t


def _stub(monkeypatch, spot=100.0, strikes=(90.0, 95.0, 100.0, 105.0, 110.0)):
    rows = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=_TODAY,
            bid=1.0, ask=1.2, last=None, open_interest=None, iv=None,
        )
        for k in strikes
        for side in ("call", "put")
    ]
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: rows
    )
    monkeypatch.setattr("routers.zerodte._spot_for_symbol", lambda sym: float(spot))
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=float(spot))},
    )
    # No live per-contract quotes → each new leg prices off the model mark.
    monkeypatch.setattr("routers.zerodte._live_leg_quotes", lambda sym, legs: {})
    monkeypatch.setattr(
        "services.order_monitor._default_option_mark", lambda t, s, now: 1.5
    )
    monkeypatch.setattr(
        "services.order_monitor._default_unrealized_for", lambda t, s, now: 25.0
    )


def test_roll_up_closes_and_reopens_shifted(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], tp_premium_mult=2.0, stop_loss=95.0)
    _stub(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/roll", json={"trade_id": tid, "strike_shift": 5}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["closed"] == tid
    old = _get(session_factory, tid)
    assert old.status == "closed" and "rolled +5" in (old.notes or "")
    new = _get(session_factory, body["opened"])
    assert new.status == "open"
    assert new.legs[0]["strike"] == 105.0
    assert new.strategy == "long_call"
    assert new.tp_premium_mult == 2.0     # premium exits carry over
    assert new.stop_loss is None          # stale underlying brackets dropped
    assert "rolled from" in (new.notes or "")


def test_roll_to_atm_recenters_the_anchor_leg(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    # Straddle drifted 5 points OTM (legs at 95, entry underlying 100 → ATM 100).
    tid = _seed(
        session_factory, c["id"], strategy="long_straddle",
        _legs=[_leg("call", "buy", 95.0, 1.0), _leg("put", "buy", 95.0, 1.0)],
    )
    _stub(monkeypatch)
    res = auth_client.post("/api/zerodte/roll", json={"trade_id": tid, "to_atm": True})
    assert res.status_code == 200, res.text
    new = _get(session_factory, res.json()["opened"])
    assert [leg["strike"] for leg in new.legs] == [100.0, 100.0]


def test_roll_already_atm_409(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])  # strike 100 = ATM at spot 100
    _stub(monkeypatch)
    res = auth_client.post("/api/zerodte/roll", json={"trade_id": tid, "to_atm": True})
    assert res.status_code == 409
    assert _get(session_factory, tid).status == "open"


def test_roll_to_unlisted_strike_422_position_untouched(
    auth_client, session_factory, monkeypatch
):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    _stub(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/roll", json={"trade_id": tid, "strike_shift": 7}
    )
    assert res.status_code == 422
    assert "not" in res.json()["detail"] and "listed" in res.json()["detail"]
    assert _get(session_factory, tid).status == "open"


def test_roll_param_validation(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    _stub(monkeypatch)
    res = auth_client.post("/api/zerodte/roll", json={"trade_id": tid})
    assert res.status_code == 422
    res = auth_client.post(
        "/api/zerodte/roll",
        json={"trade_id": tid, "strike_shift": 5, "to_atm": True},
    )
    assert res.status_code == 422


def test_roll_requires_open_owned_position(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    closed = _seed(session_factory, c["id"], status="closed")
    _stub(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/roll", json={"trade_id": closed, "strike_shift": 5}
    )
    assert res.status_code == 409
    ghost = _seed(session_factory, c["id"] + 999)  # not the active combine
    res = auth_client.post(
        "/api/zerodte/roll", json={"trade_id": ghost, "strike_shift": 5}
    )
    assert res.status_code == 404


def test_roll_margin_gate_refuses_before_closing(
    auth_client, session_factory, monkeypatch
):
    """A roll into a requirement the balance can't hold is refused with the
    position UNTOUCHED (the close never books)."""
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "sell", 100.0, 1.0)]
    tid = _seed(session_factory, c["id"], strategy="short_call", _legs=legs)
    _stub(monkeypatch)
    # Naked rate cranked to 5× spot → new requirement ≈ $50k+ > balance.
    monkeypatch.setattr(settings, "margin_naked_pct", 5.0)
    monkeypatch.setattr(settings, "margin_naked_min_pct", 5.0)
    res = auth_client.post(
        "/api/zerodte/roll", json={"trade_id": tid, "strike_shift": 5}
    )
    assert res.status_code == 422
    assert "buying power" in res.json()["detail"]
    assert _get(session_factory, tid).status == "open"
