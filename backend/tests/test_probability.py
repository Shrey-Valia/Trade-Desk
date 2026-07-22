"""Closed-form prob-ITM / POP — risk-neutral lognormal sanity checks."""

from __future__ import annotations

import pytest

from calculations.probability import (
    pop_from_curve,
    pop_long,
    prob_above,
    prob_below,
    prob_itm,
)

# A liquid-ish 0DTE shape: spot 500, ~6.5h to the bell, 20% vol.
S, T, R, SIG = 500.0, 6.5 / (24 * 365), 0.045, 0.20


def test_prob_above_below_are_complements():
    p_up = prob_above(S, 505.0, T, R, SIG)
    assert prob_below(S, 505.0, T, R, SIG) == pytest.approx(1.0 - p_up)
    assert 0.0 < p_up < 0.5  # OTM upside level → less than a coin flip


def test_atm_is_roughly_a_coin_flip():
    assert prob_above(S, 500.0, T, R, SIG) == pytest.approx(0.5, abs=0.05)


def test_prob_itm_call_put_split_the_line():
    call = prob_itm(S, 500.0, T, R, SIG, "call")
    put = prob_itm(S, 500.0, T, R, SIG, "put")
    assert call + put == pytest.approx(1.0)
    # Deep ITM call ≈ certainty; deep OTM ≈ zero.
    assert prob_itm(S, 400.0, T, R, SIG, "call") > 0.999
    assert prob_itm(S, 600.0, T, R, SIG, "call") < 0.001


def test_degenerate_time_collapses_to_step():
    assert prob_above(S, 499.0, 0.0, R, SIG) == 1.0
    assert prob_above(S, 501.0, 0.0, R, SIG) == 0.0


def test_pop_long_call_needs_move_past_breakeven():
    # Long 500C at $2 → BE 502: POP < prob-ITM (must clear the premium too).
    pop = pop_long(S, [502.0], T, R, SIG, "call")
    itm = prob_itm(S, 500.0, T, R, SIG, "call")
    assert pop is not None and pop < itm
    assert 0.0 < pop < 0.5


def test_pop_long_put_mirrors():
    pop = pop_long(S, [498.0], T, R, SIG, "put")
    assert pop is not None and 0.0 < pop < 0.5


def test_pop_long_straddle_sums_both_tails():
    pop = pop_long(S, [496.0, 504.0], T, R, SIG, None)
    lo = prob_below(S, 496.0, T, R, SIG)
    hi = prob_above(S, 504.0, T, R, SIG)
    assert pop == pytest.approx(lo + hi)
    assert 0.0 < pop < 1.0


def test_pop_unpriceable_shape_returns_none():
    assert pop_long(S, [], T, R, SIG, "call") is None
    assert pop_long(S, [490.0, 495.0, 505.0], T, R, SIG, None) is None


# --- generic curve-region POP ------------------------------------------------


def test_pop_from_curve_condor_profits_inside_the_band():
    # Iron-condor-shaped payoff: +$50 inside [495, 505], losing outside.
    payoff = lambda s: 50.0 if 495.0 < s < 505.0 else -100.0  # noqa: E731
    pop = pop_from_curve(S, [495.0, 505.0], T, R, SIG, payoff)
    expected = prob_above(S, 495.0, T, R, SIG) - prob_above(S, 505.0, T, R, SIG)
    assert pop == pytest.approx(expected)


def test_pop_from_curve_credit_spread_single_breakeven():
    # Bull put credit spread: profit ABOVE the breakeven.
    payoff = lambda s: 30.0 if s > 497.0 else -70.0  # noqa: E731
    pop = pop_from_curve(S, [497.0], T, R, SIG, payoff)
    assert pop == pytest.approx(prob_above(S, 497.0, T, R, SIG))
    assert pop > 0.5  # spot already above the breakeven


def test_pop_from_curve_no_crossing_is_all_or_nothing():
    assert pop_from_curve(S, [], T, R, SIG, lambda s: 10.0) == 1.0
    assert pop_from_curve(S, [], T, R, SIG, lambda s: -10.0) == 0.0
