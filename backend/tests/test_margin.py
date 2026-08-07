"""Margin / buying-power model — pure requirements + the open-path gate.

Requirement rules under test (calculations/margin.py): defined-risk = max
loss at expiry; naked sides = Reg-T-style (pct·spot − OTM, floored), both
sides naked = greater side + other side's short premium. Gate: new structure
requirement + book requirement must fit the realized balance.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime

import pytest

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from calculations.margin import book_requirement, structure_requirement
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


# --- pure requirements -------------------------------------------------------


def test_long_call_requires_the_debit():
    assert structure_requirement([_leg("call", "buy", 100, 1.5)], 100.0) == 150.0


def test_long_straddle_requires_total_debit():
    legs = [_leg("call", "buy", 100, 1.1), _leg("put", "buy", 100, 1.0)]
    assert structure_requirement(legs, 100.0) == 210.0


def test_credit_spread_requires_width_minus_credit():
    # Sell 100P at 1.00, buy 95P at 0.40 → credit 0.60, width 5 → req $440.
    legs = [_leg("put", "sell", 100, 1.0), _leg("put", "buy", 95, 0.4)]
    assert structure_requirement(legs, 100.0) == pytest.approx(440.0)


def test_iron_condor_requires_worst_wing():
    legs = [
        _leg("put", "buy", 90, 0.2), _leg("put", "sell", 95, 0.5),
        _leg("call", "sell", 105, 0.5), _leg("call", "buy", 110, 0.2),
    ]
    # Net credit 0.6; either breached wing loses width 5 − 0.6 = 4.4 → $440.
    assert structure_requirement(legs, 100.0) == pytest.approx(440.0)


def test_naked_call_uses_reg_t_rate():
    # ATM naked call, spot 100: (0.20×100 − 0 + 1.0) × 100 = $2,100.
    assert structure_requirement(
        [_leg("call", "sell", 100, 1.0)], 100.0
    ) == pytest.approx(2100.0)


def test_naked_action_variant_is_sized_as_short_not_defined_risk():
    """Regression (P2): a short leg written with a non-canonical action string
    (e.g. 'short' from a rogue DB writer) must draw the SAME Reg-T naked
    requirement as 'sell'. Previously _sign counted it net-short but the naked
    helpers recognized only 'sell', so the naked requirement came back $0 and
    an uncovered write was sized as defined-risk (near-zero collateral)."""
    canonical = structure_requirement([_leg("call", "sell", 100, 1.0)], 100.0)
    variant = structure_requirement([_leg("call", "short", 100, 1.0)], 100.0)
    assert variant == pytest.approx(canonical) == pytest.approx(2100.0)
    # And it is NOT collapsed to the tiny defined-risk (debit-like) number.
    assert variant > 1000.0


def test_naked_call_otm_reduction_with_floor():
    # 30-pts OTM: 20%×100 − 30 < 0 → floor 10%×spot → (10 + 0.1)×100 = $1,010.
    assert structure_requirement(
        [_leg("call", "sell", 130, 0.1)], 100.0
    ) == pytest.approx(1010.0)


def test_naked_put_floor_uses_strike():
    # Deep OTM put: floor = 10% × strike 70 → (7 + 0.05) × 100 = $705.
    assert structure_requirement(
        [_leg("put", "sell", 70, 0.05)], 100.0
    ) == pytest.approx(705.0)


def test_short_straddle_greater_side_plus_other_premium():
    legs = [_leg("call", "sell", 100, 1.1), _leg("put", "sell", 100, 1.0)]
    # call side (0.20×100 + 1.1)×100 = 2110 ≥ put side 2100 → 2110 + put prem 100.
    assert structure_requirement(legs, 100.0) == pytest.approx(2210.0)


def test_ratio_spread_sums_naked_and_bounded():
    # Buy 1 100C, sell 2 105C → net short 1 call: naked req on the 105 short
    # (0.20×100 − 5 + 0.5)×100 = $1,550 PLUS the bounded region's max loss
    # (the 0.10 net debit below the strikes = $10). SUM, not max — review
    # finding 5: max() understated mixed structures.
    legs = [_leg("call", "buy", 100, 1.1), _leg("call", "sell", 105, 0.5, 2)]
    assert structure_requirement(legs, 100.0) == pytest.approx(1560.0)


def test_put_ratio_spread_no_longer_understated():
    """The review's worked example: sell 2× 95P @1.00 / buy 1× 90P @0.50 at
    spot 100. Old max() rule returned $1,600 (~24% under broker sum-of-parts
    ≈ $2,100); the sum rule returns naked $1,600 + bounded $850 = $2,450 —
    over-conservative, the correct side for a margin model to err on."""
    legs = [_leg("put", "sell", 95, 1.0, 2), _leg("put", "buy", 90, 0.5)]
    assert structure_requirement(legs, 100.0) == pytest.approx(2450.0)


def test_requirement_scales_with_contracts():
    legs = [_leg("put", "sell", 100, 1.0, 3), _leg("put", "buy", 95, 0.4, 3)]
    assert structure_requirement(legs, 100.0) == pytest.approx(3 * 440.0)


def test_book_requirement_sums_structures():
    a = [_leg("call", "buy", 100, 1.0)]
    b = [_leg("put", "sell", 100, 1.0)]
    total = book_requirement([(a, 100.0), (b, 100.0)])
    assert total == pytest.approx(100.0 + 2100.0)


# --- the open-path gate ------------------------------------------------------


def _stub_market(monkeypatch, spot=100.0, prem_bid=1.0, prem_ask=1.2):
    strikes = (spot - 5, spot, spot + 5)
    rows = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=_TODAY,
            bid=prem_bid, ask=prem_ask, last=None, open_interest=None, iv=None,
        )
        for k in strikes
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


def test_debit_open_passes_within_balance(auth_client, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    res = auth_client.post(
        "/api/zerodte/open", json={"symbol": "SPY", "action": "buy", "contracts": 1}
    )
    assert res.status_code == 201, res.text


def test_naked_short_rejected_when_requirement_exceeds_balance(auth_client, monkeypatch):
    """The audit's exploit: naked premium used to be free. At spot 5000 a
    short straddle needs ~$100k+ — a 50K combine must be refused."""
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, spot=5000.0)
    res = auth_client.post(
        "/api/zerodte/open", json={"symbol": "SPY", "action": "sell", "contracts": 1}
    )
    assert res.status_code == 422
    assert "buying power" in res.json()["detail"]


def test_working_short_order_reserves_margin_at_placement(auth_client, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, spot=5000.0)
    res = auth_client.post(
        "/api/zerodte/open-leg",
        json={
            "symbol": "SPY", "side": "call", "action": "sell", "strike": 5000.0,
            "contracts": 1, "entry_price": 1.0, "order_type": "limit",
            "limit_price": 1.0,
        },
    )
    assert res.status_code == 422
    assert "buying power" in res.json()["detail"]


def test_gate_disabled_by_config(auth_client, monkeypatch):
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch, spot=5000.0)
    monkeypatch.setattr(settings, "margin_enforcement_enabled", False)
    res = auth_client.post(
        "/api/zerodte/open", json={"symbol": "SPY", "action": "sell", "contracts": 1}
    )
    assert res.status_code == 201, res.text


def test_committed_book_counts_against_new_opens(auth_client, session_factory, monkeypatch):
    """Seed a book already committing most of the balance; a new naked short
    that would fit an empty book is refused against the remaining BP."""
    c = make_combine(auth_client, "50K")
    s = session_factory()
    t = Trade(
        symbol="SPY", strategy="short_put", entry_date=datetime.now(UTC),
        entry_underlying_price=1000.0, net_debit_credit=-10.0, is_paper=True,
        tier="50K", combine_id=c["id"], status="open",
    )
    # 3× naked short put at strike 1000 (stays under the 5-contract scaling
    # cap once the 2-leg straddle adds 2 more). The gate reprices the SPY
    # book at the live hinted spot (500): base = max(0.20×500, 0.10×1000)
    # = 100 → (100 + 60) × 100 × 3 = $48k committed.
    t.legs = [_leg("put", "sell", 1000.0, 60.0, 3)]
    s.add(t)
    s.commit()
    s.close()
    # No independent live fetch — the book prices off the gate's spot hint.
    monkeypatch.setattr("routers.zerodte._spot_for_symbol", lambda sym: None)
    _stub_market(monkeypatch, spot=500.0)
    # New short straddle at spot 500 needs ~$10.2k > 50k − 48k = $2k left.
    res = auth_client.post(
        "/api/zerodte/open", json={"symbol": "SPY", "action": "sell", "contracts": 1}
    )
    assert res.status_code == 422
    assert "buying power" in res.json()["detail"]


def test_account_state_exposes_margin_and_bp(auth_client, session_factory, monkeypatch):
    c = make_combine(auth_client, "50K")
    s = session_factory()
    t = Trade(
        symbol="SPY", strategy="long_call", entry_date=datetime.now(UTC),
        entry_underlying_price=100.0, net_debit_credit=1.5, is_paper=True,
        tier="50K", combine_id=c["id"], status="open",
    )
    t.legs = [_leg("call", "buy", 100.0, 1.5)]
    s.add(t)
    s.commit()
    s.close()
    monkeypatch.setattr("routers.zerodte._spot_for_symbol", lambda sym: None)
    res = auth_client.get("/api/account/state")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["margin_used"] == pytest.approx(150.0)
    assert body["buying_power"] == pytest.approx(50_000.0 - 150.0)
