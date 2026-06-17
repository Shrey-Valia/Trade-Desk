"""Pre-trade contract-preview payoff math (calculations.intraday_analytics
.compute_contract_preview) — the engine behind the contract-detail panel."""

from __future__ import annotations

from calculations.intraday_analytics import compute_contract_preview

_RATE = 0.04
_IV = 0.20
_T = 1.0 / 365.0  # ~one day to expiry


def _leg(side: str, strike: float, price: float, contracts: int = 1) -> dict:
    return {
        "side": side,
        "action": "buy",
        "strike": strike,
        "contracts": contracts,
        "entry_price": price,
    }


def test_long_call_payoff():
    p = compute_contract_preview(
        spot=100.0, rate=_RATE, iv=_IV, t_now=_T, legs=[_leg("call", 100.0, 2.0)]
    )
    assert p.cost == 200.0                 # 2 × 100 × 1
    assert p.entry_price == 2.0
    assert p.max_loss == -200.0            # long option: max loss = debit
    assert p.max_profit is None            # unbounded upside
    # Break-even = strike + debit = 102.
    assert len(p.breakevens) == 1
    assert abs(p.breakevens[0] - 102.0) < 0.5
    assert p.greeks["delta"] > 0           # long call is long delta


def test_long_put_payoff():
    p = compute_contract_preview(
        spot=100.0, rate=_RATE, iv=_IV, t_now=_T, legs=[_leg("put", 100.0, 2.0)]
    )
    assert p.max_loss == -200.0
    # Bounded gain: intrinsic at S→0 minus cost = (100 − 2) × 100.
    assert p.max_profit == 9800.0
    assert len(p.breakevens) == 1
    assert abs(p.breakevens[0] - 98.0) < 0.5
    assert p.greeks["delta"] < 0           # long put is short delta


def test_long_straddle_two_breakevens():
    p = compute_contract_preview(
        spot=100.0,
        rate=_RATE,
        iv=_IV,
        t_now=_T,
        legs=[_leg("call", 100.0, 2.0), _leg("put", 100.0, 2.0)],
    )
    assert p.cost == 400.0                  # 4 × 100
    assert p.max_loss == -400.0
    assert p.max_profit is None             # net long call → unbounded up
    # Break-evens at strike ± total premium = 96 and 104.
    assert len(p.breakevens) == 2
    los = sorted(p.breakevens)
    assert abs(los[0] - 96.0) < 0.5
    assert abs(los[1] - 104.0) < 0.5


def test_payoff_arrays_aligned_and_dollarized():
    p = compute_contract_preview(
        spot=100.0, rate=_RATE, iv=_IV, t_now=_T, legs=[_leg("call", 100.0, 2.0)]
    )
    assert len(p.prices) == len(p.payoff_today) == len(p.payoff_expiration) == 81
    # Deep ITM at expiry pays ~ (S − strike − debit) × 100; far OTM = −cost.
    assert p.payoff_expiration[-1] > 0
    assert p.payoff_expiration[0] == -200.0
