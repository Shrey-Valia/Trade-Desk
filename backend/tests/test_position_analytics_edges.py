"""Adversarial edge cases for position analytics.

The hook is only credible if the numbers are. These tests probe each
failure mode that would produce a visible-wrong number on a trader's
screen: divergent IV solves, missing or duplicate breakevens, sign-flips
on credit-position P&L, and division-by-zero at expiration.

Naming convention: each test name describes the FAILURE it would catch.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from calculations.position_analytics import (
    DEFAULT_IV,
    build_legs_from_journal,
    compute_analytics,
    implied_vol,
    shift_legs_to_dte,
)


TODAY = date(2026, 5, 22)
ENTRY = TODAY - timedelta(days=3)
RATE = 0.045
DTE_30 = (TODAY + timedelta(days=27)).isoformat()
DTE_14 = (TODAY + timedelta(days=14)).isoformat()
DTE_1 = (TODAY + timedelta(days=1)).isoformat()


def _build(legs, spot_entry=100.0):
    return build_legs_from_journal(
        legs, today=TODAY, rate=RATE,
        spot_at_entry=spot_entry, entry_date=ENTRY,
    )


# =============================================================================
# BUCKET 1 — IV back-solve robustness
# =============================================================================


def test_iv_solve_deep_itm_call_converges():
    """Deep ITM call: market price ~= intrinsic + small. Solver mustn't fail."""
    iv = implied_vol(
        market_price=101.5, spot=300.0, strike=200.0,
        T_years=21 / 365, rate=RATE, option_type="call",
    )
    assert iv is not None, "deep ITM should still converge"
    assert 0.01 < iv < 3.0


def test_iv_solve_deep_otm_call_with_tiny_price_converges():
    """Deep OTM with $0.05 premium — solver returns a high but finite IV."""
    iv = implied_vol(
        market_price=0.05, spot=100.0, strike=200.0,
        T_years=14 / 365, rate=RATE, option_type="call",
    )
    assert iv is not None
    assert 0.1 < iv < 5.0


def test_iv_solve_below_intrinsic_returns_none():
    """Market price < intrinsic is an arbitrage; no valid IV exists.
    Must return None — NOT a wild IV that would garbage the analytics."""
    iv = implied_vol(
        market_price=5.0, spot=200.0, strike=180.0,
        T_years=21 / 365, rate=RATE, option_type="call",
    )
    assert iv is None


def test_iv_solve_zero_and_negative_price_return_none():
    assert implied_vol(market_price=0.0, spot=100, strike=100,
                       T_years=21 / 365, rate=RATE, option_type="call") is None
    assert implied_vol(market_price=-1.0, spot=100, strike=100,
                       T_years=21 / 365, rate=RATE, option_type="call") is None


def test_iv_solve_one_day_to_expiry_still_converges():
    """1-DTE ATM is steep — solver shouldn't choke on the high gradient."""
    iv = implied_vol(
        market_price=0.80, spot=100.0, strike=100.0,
        T_years=1 / 365, rate=RATE, option_type="call",
    )
    assert iv is not None
    assert 0.05 < iv < 3.0


def test_position_analytics_degrades_when_one_leg_iv_fails():
    """A single bad leg shouldn't poison the whole position's analytics.
    The remaining legs' implied IVs (or DEFAULT_IV) carry the math."""
    bad_leg_entry = 0.001  # below intrinsic for an ATM call
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": bad_leg_entry},
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 3.50},
    ]
    legs, iv, source = _build(legs_in, spot_entry=100.0)
    # Source should still be "implied_from_entry" because the put solved.
    assert source == "implied_from_entry"
    assert iv > 0

    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    # No NaN/Inf anywhere in the payload.
    assert all(math.isfinite(v) for v in result.payoff_today)
    assert all(math.isfinite(v) for v in result.payoff_expiration)
    assert all(math.isfinite(v) for v in result.breakevens_today)
    assert all(math.isfinite(v) for v in result.breakevens_expiration)


def test_position_analytics_uses_default_iv_when_all_legs_fail():
    """If every leg's entry_price is unusable, fall back to DEFAULT_IV."""
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 0.0},
    ]
    legs, iv, source = _build(legs_in, spot_entry=100.0)
    assert source == "default"
    assert iv == DEFAULT_IV


# =============================================================================
# BUCKET 2 — Breakeven-finding correctness
# =============================================================================


def test_long_straddle_has_exactly_two_expiration_breakevens():
    """ATM long straddle, $10 total premium → BEs at strike±10."""
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.00},
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.00},
    ]
    legs, iv, source = _build(legs_in, spot_entry=100.0)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    bes = sorted(result.breakevens_expiration)
    assert len(bes) == 2
    assert bes[0] == pytest.approx(90.0, abs=1.0)
    assert bes[1] == pytest.approx(110.0, abs=1.0)


def test_vertical_spread_has_exactly_one_breakeven():
    """Bull call spread 100/110, $3 debit → single BE at 103."""
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.00},
        {"side": "call", "action": "sell", "strike": 110.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 2.00},
    ]
    legs, iv, source = _build(legs_in, spot_entry=100.0)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    bes = result.breakevens_expiration
    assert len(bes) == 1, f"expected 1 BE for a vertical, got {bes}"
    assert bes[0] == pytest.approx(103.0, abs=0.5)


def test_iron_condor_has_exactly_two_breakevens_outside_short_strikes():
    """Short condor with $3 credit, shorts at 95/105 → BEs at 92/108."""
    legs_in = [
        {"side": "call", "action": "sell", "strike": 105.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 2.50},
        {"side": "call", "action": "buy", "strike": 110.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 1.00},
        {"side": "put", "action": "sell", "strike": 95.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 2.50},
        {"side": "put", "action": "buy", "strike": 90.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 1.00},
    ]
    legs, iv, source = _build(legs_in, spot_entry=100.0)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    bes = sorted(result.breakevens_expiration)
    assert len(bes) == 2, f"expected 2 BEs for condor, got {bes}"
    # Net credit per share: (2.5 + 2.5) - (1.0 + 1.0) = 3.0. BEs at short ± credit.
    assert bes[0] == pytest.approx(92.0, abs=0.5)
    assert bes[1] == pytest.approx(108.0, abs=0.5)


def test_breakevens_returned_sorted_and_deduplicated():
    """Any returned BE list must be sorted ascending and not contain two
    values within 0.05 (solver-noise dedupe)."""
    # Long straddle reliably produces 2 BEs across all strategies; we use
    # it to verify dedup since the curve is well-behaved.
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, iv, source = _build(legs_in)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    for be_list in (result.breakevens_expiration, result.breakevens_today):
        assert be_list == sorted(be_list)
        for i in range(len(be_list) - 1):
            assert be_list[i + 1] - be_list[i] > 0.05, (
                f"duplicate-ish BEs {be_list[i]} ≈ {be_list[i+1]}"
            )


def test_position_with_no_breakeven_in_range_returns_empty_list():
    """Long put with strike far below spot: position is -premium across
    the entire ±25% grid → no zero crossing. Must return [] cleanly."""
    legs_in = [
        {"side": "put", "action": "buy", "strike": 50.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 1.00},
    ]
    legs, iv, source = _build(legs_in, spot_entry=100.0)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    assert result.breakevens_expiration == []


def test_straddle_today_be_band_inside_expiration_band_for_both_sides():
    """The BE band geometry is identical for long and short straddles —
    both have today's BEs INSIDE the expiration BEs. The smooth time-
    valued curve crosses zero closer to the strike than the kinked
    expiration payoff does.

    What differs between long and short isn't where the band is — it's
    which side is the profit zone:
      - LONG premium: profit zone OUTSIDE the band (wider today, contracts to
        the naive 'strike ± premium' at expiration)
      - SHORT premium: profit zone INSIDE the band (narrower today, expands
        to the naive 'strike ± credit' at expiration)
    """
    long_legs = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    short_legs = [{**leg, "action": "sell"} for leg in long_legs]

    for label, legs_in in (("long", long_legs), ("short", short_legs)):
        legs, iv, source = _build(legs_in)
        result = compute_analytics(legs, spot=100.0, rate=RATE,
                                   iv_used=iv, iv_source=source)
        today = sorted(result.breakevens_today)
        expiry = sorted(result.breakevens_expiration)
        assert len(today) == 2 and len(expiry) == 2, label
        # Today's BEs INSIDE expiration BEs — for BOTH directions.
        assert today[0] > expiry[0], f"{label}: today low {today[0]} should be > expiry low {expiry[0]}"
        assert today[1] < expiry[1], f"{label}: today high {today[1]} should be < expiry high {expiry[1]}"


def test_be_band_widens_toward_expiration_as_scrubber_advances():
    """For BOTH long and short straddles, the live BE band widens out
    toward the expiration band as DTE → 0. Directionality is the same;
    only the trader's interpretation of the band flips."""
    for action in ("buy", "sell"):
        legs_in = [
            {"side": "call", "action": action, "strike": 100.0, "expiry": DTE_30,
             "contracts": 1, "entry_price": 5.0},
            {"side": "put", "action": action, "strike": 100.0, "expiry": DTE_30,
             "contracts": 1, "entry_price": 5.0},
        ]
        legs, iv, source = _build(legs_in)
        now = compute_analytics(legs, spot=100.0, rate=RATE,
                                iv_used=iv, iv_source=source)
        near = compute_analytics(legs, spot=100.0, rate=RATE,
                                  scrubber_dte_days=3,
                                  iv_used=iv, iv_source=source)
        now_band = sorted(now.breakevens_today)
        near_band = sorted(near.breakevens_today)
        now_width = now_band[1] - now_band[0]
        near_width = near_band[1] - near_band[0]
        assert near_width > now_width, (
            f"{action}: band must widen toward expiration; "
            f"now={now_width:.2f} near={near_width:.2f}"
        )


# =============================================================================
# BUCKET 3 — P&L and value sanity
# =============================================================================


def test_credit_iron_condor_pnl_goes_positive_with_decay():
    """Iron condor with $300 credit (cost_basis = -$300). Scrubbing close
    to expiration with spot still inside the profit zone should drive
    unrealized P&L POSITIVE — NOT negative (which would be the wrong
    sign for credit positions)."""
    # 95/105 short, 90/110 wings, $3 credit/share = -$300 cost basis.
    legs_in = [
        {"side": "call", "action": "sell", "strike": 105.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 2.50},
        {"side": "call", "action": "buy", "strike": 110.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 1.00},
        {"side": "put", "action": "sell", "strike": 95.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 2.50},
        {"side": "put", "action": "buy", "strike": 90.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 1.00},
    ]
    legs, iv, source = _build(legs_in)
    # Scrub right up to expiry with spot at 100 (centered in profit zone).
    near = compute_analytics(legs, spot=100.0, rate=RATE,
                             scrubber_dte_days=0,
                             iv_used=iv, iv_source=source)
    assert near.cost_basis == pytest.approx(-300.0, abs=0.01)
    # At spot=100 at expiration, all options expire worthless → keep full credit.
    assert near.unrealized_pnl == pytest.approx(300.0, abs=2.0)


def test_at_full_scrub_to_expiration_value_equals_intrinsic_payoff():
    """T=0 scrub must match the textbook expiration payoff at every
    grid price — proves the BS engine's T<=0 branch returns intrinsic
    cleanly and our shift_legs_to_dte zeroes T correctly."""
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, iv, source = _build(legs_in)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               scrubber_dte_days=0,
                               iv_used=iv, iv_source=source)
    # payoff_today (at scrubber 0) must coincide with payoff_expiration
    # pointwise, up to small interest-rate effects on the discounting.
    # We allow a couple of cents tolerance per point.
    diffs = [abs(t - e) for t, e in zip(result.payoff_today, result.payoff_expiration)]
    assert max(diffs) < 1.0, f"max diff today vs expiry at DTE=0 was {max(diffs):.4f}"


def test_long_premium_has_negative_theta():
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, iv, source = _build(legs_in)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    assert result.greeks["theta"] < 0, "long premium should bleed value daily"


def test_short_premium_has_positive_theta():
    legs_in = [
        {"side": "call", "action": "sell", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
        {"side": "put", "action": "sell", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, iv, source = _build(legs_in)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    assert result.greeks["theta"] > 0, "short premium should collect theta"


def test_long_call_has_positive_delta():
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, iv, source = _build(legs_in)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    assert result.greeks["delta"] > 0


def test_long_put_has_negative_delta():
    legs_in = [
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, iv, source = _build(legs_in)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               iv_used=iv, iv_source=source)
    assert result.greeks["delta"] < 0


# =============================================================================
# BUCKET 4 — Scrubber edge (T → 0 singularity)
# =============================================================================


def test_scrubber_to_zero_produces_finite_values_everywhere():
    """The BS formula has 1/sqrt(T) terms that explode as T → 0. The
    intrinsic-branch at T<=0 should bypass that, but verify no NaN/Inf
    leaks through into curves, BEs, or greeks at the limit."""
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
        {"side": "put", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, iv, source = _build(legs_in)
    result = compute_analytics(legs, spot=100.0, rate=RATE,
                               scrubber_dte_days=0,
                               iv_used=iv, iv_source=source)
    assert all(math.isfinite(v) for v in result.payoff_today)
    assert all(math.isfinite(v) for v in result.breakevens_today)
    assert all(math.isfinite(v) for v in result.greeks.values())
    assert math.isfinite(result.current_value)
    assert math.isfinite(result.unrealized_pnl)


def test_shift_legs_to_dte_floors_at_zero():
    """Scrubber overshooting current DTE shouldn't yield negative T."""
    legs_in = [
        {"side": "call", "action": "buy", "strike": 100.0, "expiry": DTE_30,
         "contracts": 1, "entry_price": 5.0},
    ]
    legs, _, _ = _build(legs_in)
    shifted = shift_legs_to_dte(legs, current_dte_days=27, scrubber_dte_days=27)
    assert all(leg.T >= 0 for leg in shifted)
    shifted2 = shift_legs_to_dte(legs, current_dte_days=27, scrubber_dte_days=-100)
    assert all(leg.T >= 0 for leg in shifted2)
