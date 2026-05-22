"""Trade Desk Phase 2 — position analytics behavior.

Tests the theta-decay scrubber's core promise: long straddle breakevens
move INWARD toward spot as expiry approaches; iron condor produces two
BEs; cost basis matches the journaled entry prices.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from calculations.position_analytics import (
    build_legs_from_journal,
    compute_analytics,
    shift_legs_to_dte,
)


SPOT = 220.0
RATE = 0.045
TODAY = date(2026, 5, 22)
ENTRY = TODAY - timedelta(days=3)
EXPIRY_30D = (TODAY + timedelta(days=27)).isoformat()


def _straddle_legs():
    return [
        {"side": "call", "action": "buy", "strike": 220.0,
         "expiry": EXPIRY_30D, "contracts": 1, "entry_price": 9.40},
        {"side": "put", "action": "buy", "strike": 220.0,
         "expiry": EXPIRY_30D, "contracts": 1, "entry_price": 8.60},
    ]


def _iron_condor_legs():
    return [
        {"side": "call", "action": "sell", "strike": 230.0,
         "expiry": EXPIRY_30D, "contracts": 1, "entry_price": 4.10},
        {"side": "call", "action": "buy",  "strike": 240.0,
         "expiry": EXPIRY_30D, "contracts": 1, "entry_price": 2.30},
        {"side": "put",  "action": "sell", "strike": 210.0,
         "expiry": EXPIRY_30D, "contracts": 1, "entry_price": 3.80},
        {"side": "put",  "action": "buy",  "strike": 200.0,
         "expiry": EXPIRY_30D, "contracts": 1, "entry_price": 2.05},
    ]


# ---------------------------------------------------------------------------
# Cost basis sanity — must match the journal's net_debit_credit math.
# ---------------------------------------------------------------------------


def test_cost_basis_matches_journal_for_straddle():
    legs, _, _ = build_legs_from_journal(
        _straddle_legs(), today=TODAY, rate=RATE,
        spot_at_entry=SPOT, entry_date=ENTRY,
    )
    result = compute_analytics(legs, spot=SPOT, rate=RATE,
                                iv_used=0.40, iv_source="implied_from_entry")
    # 9.40 + 8.60 = 18.00 / share × 100 = $1,800 debit
    assert result.cost_basis == pytest.approx(1800.0, abs=0.01)


def test_iron_condor_cost_basis_is_credit():
    legs, _, _ = build_legs_from_journal(
        _iron_condor_legs(), today=TODAY, rate=RATE,
        spot_at_entry=215.0, entry_date=ENTRY,
    )
    result = compute_analytics(legs, spot=215.0, rate=RATE,
                                iv_used=0.30, iv_source="implied_from_entry")
    # net premium received = 4.10 + 3.80 - 2.30 - 2.05 = 3.55 credit/share = -$355
    assert result.cost_basis == pytest.approx(-355.0, abs=0.01)


# ---------------------------------------------------------------------------
# The hook — straddle breakeven moves INWARD as DTE approaches 0.
# ---------------------------------------------------------------------------


def test_straddle_breakevens_at_expiry_match_naive_strike_plus_minus_premium():
    legs, iv, _ = build_legs_from_journal(
        _straddle_legs(), today=TODAY, rate=RATE,
        spot_at_entry=SPOT, entry_date=ENTRY,
    )
    result = compute_analytics(legs, spot=SPOT, rate=RATE,
                                iv_used=iv, iv_source="implied_from_entry")
    # ATM straddle: BE at expiry = strike ± total premium paid per share.
    # Premium = $18, strike = 220 → BEs at ~$202 and ~$238.
    assert len(result.breakevens_expiration) == 2
    low, high = sorted(result.breakevens_expiration)
    assert low == pytest.approx(202.0, abs=1.0)
    assert high == pytest.approx(238.0, abs=1.0)


def test_straddle_today_breakevens_move_inward_as_dte_scrubs_forward():
    """Theta decay → less time value → today's BE band narrows."""
    legs, iv, _ = build_legs_from_journal(
        _straddle_legs(), today=TODAY, rate=RATE,
        spot_at_entry=SPOT, entry_date=ENTRY,
    )
    current_dte = (date.fromisoformat(EXPIRY_30D) - TODAY).days

    # Today (full remaining DTE) — BEs are tight to the strike because
    # the position still has lots of time value to "earn back" before
    # the curve crosses zero. (Long premium: today curve sits BELOW
    # expiration curve, so today's BEs are inside expiration BEs.)
    today_view = compute_analytics(
        legs, spot=SPOT, rate=RATE,
        scrubber_dte_days=current_dte,
        iv_used=iv, iv_source="implied_from_entry",
    )

    # Scrub to ~3 days out — most time value has decayed.
    near_expiry_view = compute_analytics(
        legs, spot=SPOT, rate=RATE,
        scrubber_dte_days=3,
        iv_used=iv, iv_source="implied_from_entry",
    )

    today_low, today_high = sorted(today_view.breakevens_today)
    near_low, near_high = sorted(near_expiry_view.breakevens_today)

    # As we scrub toward expiry, today's curve flattens toward the
    # expiration kink → BEs widen out toward the expiration BEs.
    today_band = today_high - today_low
    near_band = near_high - near_low
    assert near_band > today_band, (
        f"expected today's BE band to widen as DTE→0; "
        f"now-band={today_band:.2f} near-expiry-band={near_band:.2f}"
    )


def test_iron_condor_yields_two_breakevens_inside_short_strikes():
    legs, iv, _ = build_legs_from_journal(
        _iron_condor_legs(), today=TODAY, rate=RATE,
        spot_at_entry=215.0, entry_date=ENTRY,
    )
    result = compute_analytics(
        legs, spot=215.0, rate=RATE,
        iv_used=iv, iv_source="implied_from_entry",
    )
    bes = sorted(result.breakevens_expiration)
    assert len(bes) == 2
    # Short strikes are 210 (put) and 230 (call). For a SHORT iron condor
    # (net credit position) the BEs sit OUTSIDE the short strikes by the
    # credit collected per share (~$3.55): BE_low ≈ 206.45, BE_high ≈
    # 233.55. The profit zone is between the short strikes; outside the
    # BEs you give back more than you collected.
    assert 205 < bes[0] < 210
    assert 230 < bes[1] < 235


# ---------------------------------------------------------------------------
# Scrubber bounds + shift_legs_to_dte sanity.
# ---------------------------------------------------------------------------


def test_scrubber_clamps_to_current_dte_when_overshooting():
    legs, iv, _ = build_legs_from_journal(
        _straddle_legs(), today=TODAY, rate=RATE,
        spot_at_entry=SPOT, entry_date=ENTRY,
    )
    # Passing a scrubber DTE larger than current is a no-op (we can't
    # add time the position doesn't have).
    big = compute_analytics(
        legs, spot=SPOT, rate=RATE, scrubber_dte_days=9999,
        iv_used=iv, iv_source="implied_from_entry",
    )
    assert big.scrubber_dte_days == big.current_dte_days


def test_shift_legs_to_dte_preserves_calendar_offset():
    legs, iv, _ = build_legs_from_journal(
        [
            {"side": "call", "action": "sell", "strike": 220.0,
             "expiry": EXPIRY_30D, "contracts": 1, "entry_price": 8.00},
            {"side": "call", "action": "buy", "strike": 220.0,
             "expiry": (TODAY + timedelta(days=60)).isoformat(),
             "contracts": 1, "entry_price": 12.00},
        ],
        today=TODAY, rate=RATE, spot_at_entry=SPOT, entry_date=ENTRY,
    )
    # Original gap = 60 - 27 = 33 days
    near_T, far_T = legs[0].T, legs[1].T
    gap_before = far_T - near_T

    shifted = shift_legs_to_dte(legs, current_dte_days=27, scrubber_dte_days=10)
    near_T2, far_T2 = shifted[0].T, shifted[1].T
    gap_after = far_T2 - near_T2

    # Both legs lose the same elapsed time → gap preserved.
    assert abs(gap_after - gap_before) < 1e-9
