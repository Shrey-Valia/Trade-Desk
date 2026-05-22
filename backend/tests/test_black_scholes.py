"""Black-Scholes pricing, greeks, strategy payoff."""

import math

import numpy as np
import pytest

from calculations.black_scholes import (
    Leg,
    breakevens,
    bs_greeks,
    bs_price,
    cost_basis,
    current_value,
    has_unlimited_gain,
    has_unlimited_loss,
    payoff_at_expiry,
    sum_greeks,
)


def _leg(**kw):
    base = dict(strike=100.0, type="call", side="long", quantity=1, iv=0.30, T=0.25, premium=0.0)
    base.update(kw)
    return Leg(**base)


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def test_atm_call_price_positive():
    p = bs_price(S=100, K=100, T=0.25, r=0.04, sigma=0.30, option_type="call")
    assert p > 0
    # ATM call ≈ S * sigma * sqrt(T/2π); rough sanity bounds.
    assert 4.0 < p < 8.0


def test_put_call_parity():
    # C - P = S - K * e^(-rT)
    S, K, T, r, sigma = 100, 105, 0.5, 0.04, 0.25
    c = bs_price(S, K, T, r, sigma, "call")
    p = bs_price(S, K, T, r, sigma, "put")
    assert c - p == pytest.approx(S - K * math.exp(-r * T), abs=1e-6)


def test_intrinsic_at_expiry():
    # T = 0 → return intrinsic, no math blowup.
    assert bs_price(110, 100, T=0, r=0.04, sigma=0.30, option_type="call") == 10.0
    assert bs_price(90, 100, T=0, r=0.04, sigma=0.30, option_type="put") == 10.0
    assert bs_price(95, 100, T=0, r=0.04, sigma=0.30, option_type="call") == 0.0


def test_deep_otm_no_nan():
    # Strike 1000 vs spot 100, short T → should price near 0, no NaN.
    p = bs_price(100, 1000, T=0.05, r=0.04, sigma=0.30, option_type="call")
    assert math.isfinite(p)
    assert 0 <= p < 0.01


def test_low_sigma_clamped():
    # sigma=0 would cause /0; clamp guards against NaN.
    p = bs_price(100, 100, T=0.25, r=0.04, sigma=0.0, option_type="call")
    assert math.isfinite(p)
    assert p >= 0


# ---------------------------------------------------------------------------
# Greeks
# ---------------------------------------------------------------------------


def test_greeks_basic_signs():
    g = bs_greeks(S=100, K=100, T=0.25, r=0.04, sigma=0.30, option_type="call")
    # ATM call: delta ≈ 0.5, gamma > 0, theta < 0, vega > 0.
    assert 0.4 < g["delta"] < 0.6
    assert g["gamma"] > 0
    assert g["theta"] < 0
    assert g["vega"] > 0


def test_put_delta_negative():
    g = bs_greeks(S=100, K=100, T=0.25, r=0.04, sigma=0.30, option_type="put")
    assert -0.6 < g["delta"] < -0.4


def test_greeks_zero_at_expiry():
    g = bs_greeks(S=110, K=100, T=0, r=0.04, sigma=0.30, option_type="call")
    assert g == {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}


def test_greeks_deep_otm_finite_and_small():
    g = bs_greeks(S=100, K=1000, T=0.05, r=0.04, sigma=0.30, option_type="call")
    for v in g.values():
        assert math.isfinite(v)
    assert abs(g["delta"]) < 1e-3


# ---------------------------------------------------------------------------
# Strategy payoff
# ---------------------------------------------------------------------------


def test_long_call_payoff_at_expiry():
    legs = [_leg(strike=100, type="call", side="long", premium=2.0)]
    prices = np.array([90.0, 100.0, 102.0, 110.0])
    pnl = payoff_at_expiry(legs, prices)
    # Below K: lose premium. Above K: max(S-K,0) - premium.
    assert pnl.tolist() == pytest.approx([-2.0, -2.0, 0.0, 8.0])


def test_long_straddle_payoff_diamond():
    legs = [
        _leg(strike=100, type="call", side="long", premium=3.0),
        _leg(strike=100, type="put", side="long", premium=3.0),
    ]
    prices = np.array([90.0, 100.0, 110.0])
    pnl = payoff_at_expiry(legs, prices)
    # At-the-money loss = total premium = 6. Wings: |move| - 6.
    assert pnl.tolist() == pytest.approx([4.0, -6.0, 4.0])


def test_bull_call_spread_capped():
    legs = [
        _leg(strike=100, type="call", side="long", premium=4.0),
        _leg(strike=110, type="call", side="short", premium=2.0),
    ]
    prices = np.array([90.0, 100.0, 110.0, 130.0])
    pnl = payoff_at_expiry(legs, prices)
    # Net debit = 2. Below 100: lose 2. Above 110: max gain = 10 - 2 = 8.
    assert pnl.tolist() == pytest.approx([-2.0, -2.0, 8.0, 8.0])


def test_cost_basis_credit_negative():
    # Net short = collect premium = negative cost basis.
    legs = [_leg(strike=100, type="call", side="short", premium=3.0)]
    assert cost_basis(legs) == -3.0


def test_breakevens_long_call():
    legs = [_leg(strike=100, type="call", side="long", premium=2.0)]
    prices = np.linspace(90, 110, 201)
    be = breakevens(prices, payoff_at_expiry(legs, prices))
    assert len(be) == 1
    assert be[0] == pytest.approx(102.0, abs=0.1)


def test_breakevens_long_straddle_two_crossings():
    legs = [
        _leg(strike=100, type="call", side="long", premium=3.0),
        _leg(strike=100, type="put", side="long", premium=3.0),
    ]
    prices = np.linspace(80, 120, 401)
    be = breakevens(prices, payoff_at_expiry(legs, prices))
    assert len(be) == 2
    assert be[0] == pytest.approx(94.0, abs=0.1)
    assert be[1] == pytest.approx(106.0, abs=0.1)


# ---------------------------------------------------------------------------
# Unlimited loss / gain
# ---------------------------------------------------------------------------


def test_short_call_marked_unlimited_loss():
    legs = [_leg(strike=100, type="call", side="short", premium=3.0)]
    assert has_unlimited_loss(legs) is True
    assert has_unlimited_gain(legs) is False


def test_long_call_marked_unlimited_gain():
    legs = [_leg(strike=100, type="call", side="long", premium=2.0)]
    assert has_unlimited_gain(legs) is True
    assert has_unlimited_loss(legs) is False


def test_bull_call_spread_bounded_both_sides():
    legs = [
        _leg(strike=100, type="call", side="long"),
        _leg(strike=110, type="call", side="short"),
    ]
    assert has_unlimited_gain(legs) is False
    assert has_unlimited_loss(legs) is False


def test_naked_short_put_not_marked_unlimited():
    # Puts are bounded because S ≥ 0 — short puts have a max loss of K.
    legs = [_leg(strike=100, type="put", side="short", premium=3.0)]
    assert has_unlimited_loss(legs) is False
    assert has_unlimited_gain(legs) is False


# ---------------------------------------------------------------------------
# Combined
# ---------------------------------------------------------------------------


def test_current_value_matches_payoff_at_expiry_when_T_zero():
    legs = [
        Leg(strike=100, type="call", side="long", quantity=1, iv=0.30, T=0.0, premium=2.0),
    ]
    prices = np.array([95.0, 100.0, 105.0, 110.0])
    expiry_pnl = payoff_at_expiry(legs, prices)
    cur_value = current_value(legs, prices, r=0.04)
    assert np.allclose(expiry_pnl, cur_value, atol=1e-6)


def test_sum_greeks_long_straddle_near_delta_neutral():
    # ATM long straddle is near-delta-neutral but not exactly zero — the
    # delta-neutral strike sits slightly above spot at K = S*exp((r+σ²/2)T).
    # What matters: net delta is small, gamma + vega are clearly positive,
    # both put + call delta contributions partially cancel.
    legs = [
        Leg(strike=100, type="call", side="long", quantity=1, iv=0.30, T=0.25, premium=3.0),
        Leg(strike=100, type="put",  side="long", quantity=1, iv=0.30, T=0.25, premium=3.0),
    ]
    g = sum_greeks(legs, spot=100, r=0.04)
    assert abs(g["delta"]) < 0.20  # would be near 1.0 for any single leg
    assert g["gamma"] > 0
    assert g["vega"] > 0
