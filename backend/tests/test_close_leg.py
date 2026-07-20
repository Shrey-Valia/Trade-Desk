"""Per-leg close — buy back one leg of a multi-leg position, rest rides."""

from __future__ import annotations

import types
from datetime import UTC, datetime

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from config import settings
from models.trade import Trade
from tests.conftest import make_combine

_TODAY = datetime.now(UTC).date()
_FEE = settings.per_contract_fee


def _leg(side, action, strike, price, contracts=1):
    return {
        "side": side, "action": action, "strike": strike,
        "expiry": _TODAY.isoformat(), "contracts": contracts,
        "entry_price": price,
    }


def _seed(session_factory, combine_id, legs, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="iron_condor",
        entry_date=datetime.now(UTC),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
        status="open",
    )
    defaults.update(kw)
    t = Trade(**defaults)
    t.legs = legs
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


def _pin_pricing(monkeypatch, mark=0.5):
    monkeypatch.setattr(
        "routers.journal.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )
    monkeypatch.setattr(
        "services.order_monitor._option_chain_rows", lambda sym: None
    )
    monkeypatch.setattr(
        "services.order_monitor._leg_model_price",
        lambda rows, leg, spot, now, rate: mark,
    )
    # Deterministic friction: no live quotes → close_friction contributes 0.
    monkeypatch.setattr(
        "routers.journal.close_friction", lambda sym, legs, stressed=False: 0.0
    )


_CONDOR = [
    _leg("put", "buy", 90.0, 0.2),
    _leg("put", "sell", 95.0, 0.5),
    _leg("call", "sell", 105.0, 0.5),
    _leg("call", "buy", 110.0, 0.2),
]


def test_close_one_leg_books_slice_and_leaves_rest(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], [dict(l) for l in _CONDOR])
    _pin_pricing(monkeypatch, mark=0.9)  # tested short call bought back at 0.9
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 2}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "open"
    assert len(body["legs"]) == 3
    assert all(
        not (leg["side"] == "call" and leg["action"] == "sell")
        for leg in body["legs"]
    )
    assert body["strategy"] == "custom"
    # Short leg bought back above entry: (0.5 − 0.9) × 100 − 2×fee.
    assert body["realized_pnl"] == round(-40.0 - 2 * _FEE, 2)
    assert "closed leg sell 105C" in (body["notes"] or "")


def test_partial_leg_qty_reduces_contracts(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "buy", 100.0, 1.0, 3), _leg("put", "buy", 100.0, 1.0, 3)]
    tid = _seed(session_factory, c["id"], legs, strategy="long_straddle")
    _pin_pricing(monkeypatch, mark=1.5)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0, "qty": 2}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["legs"][0]["contracts"] == 1
    assert body["legs"][1]["contracts"] == 3
    # Long slice: (1.5 − 1.0) × 2 × 100 − 2×2×fee.
    assert body["realized_pnl"] == round(100.0 - 4 * _FEE, 2)


def test_last_remaining_leg_gets_single_leg_strategy(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "buy", 100.0, 1.0), _leg("put", "buy", 100.0, 1.0)]
    tid = _seed(session_factory, c["id"], legs, strategy="long_straddle")
    _pin_pricing(monkeypatch)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 1}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["legs"]) == 1
    assert body["strategy"] == "long_call"
    assert body["net_debit_credit"] == 100.0  # 1.0 × 100 × 1 remaining leg


def test_single_leg_position_409(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], [_leg("call", "buy", 100.0, 1.0)],
        strategy="long_call",
    )
    _pin_pricing(monkeypatch)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0}
    )
    assert res.status_code == 409


def test_validation_errors(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "buy", 100.0, 1.0), _leg("put", "buy", 100.0, 1.0)]
    tid = _seed(session_factory, c["id"], legs, strategy="long_straddle")
    _pin_pricing(monkeypatch)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 5}
    )
    assert res.status_code == 422
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0, "qty": 9}
    )
    assert res.status_code == 400
    closed = _seed(session_factory, c["id"], legs, status="closed")
    res = auth_client.post(
        f"/api/journal/trades/{closed}/close-leg", json={"leg_index": 0}
    )
    assert res.status_code == 409


def test_copy_cascade_mirrors_leg_close_proportionally(
    auth_client, session_factory, monkeypatch
):
    """A lead's leg close cascades to open follower copies: same leg index,
    follower's own size, booked against the follower's own entry fills."""
    c = make_combine(auth_client, "50K")
    lead_legs = [
        _leg("call", "buy", 100.0, 1.0, 2), _leg("put", "buy", 100.0, 1.0, 2),
    ]
    tid = _seed(session_factory, c["id"], lead_legs, strategy="long_straddle")
    # Follower runs the same shape at 2× size with a different entry fill.
    fid = _seed(
        session_factory, c["id"],
        [_leg("call", "buy", 100.0, 0.8, 4), _leg("put", "buy", 100.0, 0.9, 4)],
        strategy="long_straddle", copied_from_trade_id=tid,
    )
    _pin_pricing(monkeypatch, mark=1.5)
    # Lead closes 1 of 2 on the call leg → follower closes 2 of 4.
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0, "qty": 1}
    )
    assert res.status_code == 200, res.text
    f = _get(session_factory, fid)
    assert f.status == "open"
    assert f.legs[0]["contracts"] == 2
    assert f.legs[1]["contracts"] == 4
    # Follower slice booked at ITS entry: (1.5 − 0.8) × 2 × 100 − 2×2×fee.
    assert f.realized_pnl == round(140.0 - 4 * _FEE, 2)
    assert "closed leg buy 100C" in (f.notes or "")


def test_copy_cascade_skips_drifted_follower(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "buy", 100.0, 1.0), _leg("put", "buy", 100.0, 1.0)]
    tid = _seed(session_factory, c["id"], legs, strategy="long_straddle")
    # Follower's leg 0 is a DIFFERENT strike — structure drifted; must be
    # left untouched rather than corrupted.
    fid = _seed(
        session_factory, c["id"],
        [_leg("call", "buy", 105.0, 1.0), _leg("put", "buy", 100.0, 1.0)],
        strategy="long_straddle", copied_from_trade_id=tid,
    )
    _pin_pricing(monkeypatch)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0}
    )
    assert res.status_code == 200
    f = _get(session_factory, fid)
    assert len(f.legs) == 2 and f.realized_pnl is None
