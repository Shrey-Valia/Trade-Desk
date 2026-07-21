"""Regression tests for review wave 8 (findings 1–6 of the branch review).

1. A resting close-limit is PULLED when the structure mutates (leg close /
   scale-out) instead of triggering/booking against legs it never described.
3. The copy cascade's proportional share rounds half-up and SKIPS followers
   whose share rounds to zero (no more forced whole-leg closes).
4. The cascade cancels still-WORKING follower copies (mirror_close's
   convention) so they can't later fill into a structure the lead no longer
   holds.
5. Mixed naked+spread margin sums naked + bounded (covered in test_margin).
6. oco_link is an all-or-nothing conditional claim; a fill that wins the
   race 409s the link instead of leaving phantom protection.
2. mirror_open gates each follower's buying power (skip-not-fail).
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
        strategy="custom",
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
    monkeypatch.setattr(
        "routers.journal.close_friction", lambda sym, legs, stressed=False: 0.0
    )


# --- finding 1: stale close-limit pulled on structure mutation ---------------


def test_leg_close_pulls_resting_close_limit(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "buy", 100.0, 1.0), _leg("put", "buy", 100.0, 1.0)]
    tid = _seed(
        session_factory, c["id"], legs,
        strategy="long_straddle", close_limit_price=3.0,
    )
    _pin_pricing(monkeypatch)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 1}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["close_limit_price"] is None
    assert "close limit pulled" in (body["notes"] or "")


def test_scale_out_pulls_resting_close_limit(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "buy", 100.0, 1.0, 3)]
    tid = _seed(
        session_factory, c["id"], legs,
        strategy="long_call", close_limit_price=2.0,
    )
    _pin_pricing(monkeypatch, mark=1.2)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/scale-out",
        json={"qty": 1, "realized_pnl": 0},
    )
    assert res.status_code == 200, res.text
    assert res.json()["close_limit_price"] is None


def test_monitor_never_fires_a_limit_after_leg_close(
    auth_client, session_factory, monkeypatch
):
    """End-to-end guard on the review's walked scenario: after the leg close
    the pulled limit must not book fabricated P&L on the remainder."""
    c = make_combine(auth_client, "50K")
    legs = [
        _leg("call", "sell", 100.0, 1.0), _leg("call", "buy", 105.0, 0.4),
        _leg("put", "sell", 95.0, 1.0), _leg("put", "buy", 90.0, 0.4),
    ]
    tid = _seed(
        session_factory, c["id"], legs,
        strategy="iron_condor", close_limit_price=-0.30,
    )
    _pin_pricing(monkeypatch, mark=0.9)
    auth_client.post(f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0})
    summary = run_order_monitor(
        session_factory=session_factory,
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 0.76,  # would have tripped the stale −0.30
        unrealized_for=lambda t, s: 0.0,
        now=datetime.combine(_TODAY, dt_time(17, 0), tzinfo=UTC),
    )
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


# --- findings 3 + 4: cascade rounding + working followers --------------------


def test_cascade_skips_follower_when_share_rounds_to_zero(
    auth_client, session_factory, monkeypatch
):
    c = make_combine(auth_client, "50K")
    lead_legs = [
        _leg("call", "buy", 100.0, 1.0, 10), _leg("put", "buy", 100.0, 1.0, 10),
    ]
    tid = _seed(session_factory, c["id"], lead_legs, strategy="long_straddle")
    fid = _seed(
        session_factory, c["id"],
        [_leg("call", "buy", 100.0, 1.0, 1), _leg("put", "buy", 100.0, 1.0, 1)],
        strategy="long_straddle", copied_from_trade_id=tid,
    )
    _pin_pricing(monkeypatch)
    # Lead trims 1 of 10 (10%) — the 1-lot follower's share rounds to 0 and
    # it must be left whole (the old max(1, …) closed its entire leg).
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0, "qty": 1}
    )
    assert res.status_code == 200, res.text
    f = _get(session_factory, fid)
    assert len(f.legs) == 2 and f.legs[0]["contracts"] == 1
    assert f.realized_pnl is None


def test_cascade_rounds_half_up_not_bankers(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    lead_legs = [
        _leg("call", "buy", 100.0, 1.0, 2), _leg("put", "buy", 100.0, 1.0, 2),
    ]
    tid = _seed(session_factory, c["id"], lead_legs, strategy="long_straddle")
    fid = _seed(
        session_factory, c["id"],
        [_leg("call", "buy", 100.0, 1.0, 5), _leg("put", "buy", 100.0, 1.0, 5)],
        strategy="long_straddle", copied_from_trade_id=tid,
    )
    _pin_pricing(monkeypatch)
    # Lead closes 1 of 2 (50%): follower's share = 2.5 → half-up = 3
    # (banker's round() gave 2).
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0, "qty": 1}
    )
    assert res.status_code == 200, res.text
    assert _get(session_factory, fid).legs[0]["contracts"] == 2  # 5 − 3


def test_cascade_cancels_working_follower(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    legs = [_leg("call", "buy", 100.0, 1.0), _leg("put", "buy", 100.0, 1.0)]
    tid = _seed(session_factory, c["id"], legs, strategy="long_straddle")
    fid = _seed(
        session_factory, c["id"], [dict(l) for l in legs],
        strategy="long_straddle", copied_from_trade_id=tid,
        status="working", order_type="limit", limit_price=1.8,
    )
    _pin_pricing(monkeypatch)
    res = auth_client.post(
        f"/api/journal/trades/{tid}/close-leg", json={"leg_index": 0}
    )
    assert res.status_code == 200, res.text
    f = _get(session_factory, fid)
    assert f.status == "cancelled"
    assert "lead closed a leg" in (f.notes or "")


# --- finding 6: oco_link all-or-nothing claim ---------------------------------


def test_oco_link_409s_when_an_order_fills_mid_link(auth_client, session_factory):
    """Simulate the race's post-state: one id already OPEN by the time the
    conditional claim runs → the whole link must fail and neither row may
    carry a group."""
    c = make_combine(auth_client, "50K")
    a = _seed(
        session_factory, c["id"], [_leg("call", "buy", 100.0, 1.0)],
        strategy="long_call", status="working", order_type="limit", limit_price=1.0,
    )
    b = _seed(
        session_factory, c["id"], [_leg("put", "buy", 100.0, 1.0)],
        strategy="long_put", status="working", order_type="limit", limit_price=1.0,
    )
    # a fills between the router's status read and the claim: emulate by
    # flipping it open through the DB (the claim, not the pre-read, decides).
    import routers.journal as journal_router

    original = journal_router._owned_trade

    def _flip_then_return(session, user, tid):
        t = original(session, user, tid)
        if tid == a:
            session.execute(
                __import__("sqlalchemy").update(Trade)
                .where(Trade.id == a)
                .values(status="open")
                .execution_options(synchronize_session=False)
            )
        return t

    journal_router._owned_trade, patched = _flip_then_return, True
    try:
        res = auth_client.post(
            "/api/journal/orders/oco-link", json={"trade_ids": [a, b]}
        )
    finally:
        if patched:
            journal_router._owned_trade = original
    assert res.status_code == 409
    assert _get(session_factory, a).oco_group is None
    assert _get(session_factory, b).oco_group is None


# --- finding 2: mirror_open margin gate ---------------------------------------


def _stub_market(monkeypatch, spot):
    rows = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=_TODAY,
            bid=1.0, ask=1.2, last=None, open_interest=None, iv=None,
        )
        for k in (spot - 5, spot, spot + 5)
        for side in ("call", "put")
    ]
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: rows
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=float(spot))},
    )
    monkeypatch.setattr("routers.zerodte._spot_for_symbol", lambda sym: None)


def _enable_copy(auth_client, lead_id, follower_id):
    res = auth_client.put(
        "/api/combines/copy-config",
        json={
            "lead_combine_id": lead_id,
            "followers": [{"combine_id": follower_id, "multiplier": 1.0}],
        },
    )
    assert res.status_code == 200, res.text


def test_mirror_open_skips_follower_without_buying_power(
    auth_client, session_factory, monkeypatch
):
    """Lead opens a naked short the follower's balance can't hold — the
    follower must be SKIPPED, not handed an ungated position (finding 2)."""
    lead = make_combine(auth_client, "50K")
    follower = make_combine(auth_client, "50K", name="follower")
    _enable_copy(auth_client, lead["id"], follower["id"])
    # Reactivate the lead as the ACTIVE combine for the open.
    res = auth_client.post(f"/api/combines/{lead['id']}/activate")
    assert res.status_code == 200, res.text
    # Naked rate cranked so ONE short contract needs ≈ 5×spot×100 > 50k.
    monkeypatch.setattr(settings, "margin_naked_pct", 8.0)
    monkeypatch.setattr(settings, "margin_naked_min_pct", 8.0)
    _stub_market(monkeypatch, spot=100.0)
    # Lead ALSO can't hold it — so relax: gate lead through by pointing the
    # lead's balance high? Simpler: disable enforcement for the direct open
    # and re-enable for the mirror? The gate flag is global. Instead crank
    # rates ONLY after the lead's gate: monkeypatch _require_buying_power to
    # no-op for the direct path while the mirror uses the real math.
    monkeypatch.setattr(
        "routers.zerodte._require_buying_power",
        lambda *a, **k: None,
    )
    res = auth_client.post(
        "/api/zerodte/open",
        json={"symbol": "SPY", "action": "sell", "contracts": 1},
    )
    assert res.status_code == 201, res.text
    s = session_factory()
    follower_trades = (
        s.query(Trade).filter(Trade.combine_id == follower["id"]).all()
    )
    s.close()
    assert follower_trades == []  # skipped — no ungated mirror


def test_mirror_open_still_mirrors_when_bp_fits(
    auth_client, session_factory, monkeypatch
):
    lead = make_combine(auth_client, "50K")
    follower = make_combine(auth_client, "50K", name="follower")
    _enable_copy(auth_client, lead["id"], follower["id"])
    res = auth_client.post(f"/api/combines/{lead['id']}/activate")
    assert res.status_code == 200, res.text
    _stub_market(monkeypatch, spot=100.0)
    res = auth_client.post(
        "/api/zerodte/open",
        json={"symbol": "SPY", "action": "buy", "contracts": 1},
    )
    assert res.status_code == 201, res.text
    s = session_factory()
    follower_trades = (
        s.query(Trade).filter(Trade.combine_id == follower["id"]).all()
    )
    s.close()
    assert len(follower_trades) == 1  # small debit fits — mirrored as before
