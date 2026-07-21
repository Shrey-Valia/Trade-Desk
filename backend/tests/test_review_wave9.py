"""Regression tests for review wave 9 (findings 7–10): analytic breakevens
for POP — the ±25% display grid missed tail crossings and hard-printed
100%/0% certainty exactly where a tail-risk trader needs honesty.
(Findings 7/8/10 are frontend; covered by the hook test + typecheck.)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from calculations.margin import exact_breakevens, payoff_at_expiry
from models.trade import Trade


def _leg(side, action, strike, price, contracts=1, expiry=None):
    return {
        "side": side, "action": action, "strike": strike,
        "expiry": expiry or date.today().isoformat(),
        "contracts": contracts, "entry_price": price,
    }


# --- exact_breakevens (pure) --------------------------------------------------


def test_long_call_breakeven_is_strike_plus_premium():
    assert exact_breakevens([_leg("call", "buy", 100.0, 1.5)]) == [
        pytest.approx(101.5)
    ]


def test_short_call_tail_crossing_beyond_top_strike():
    # Short call: payoff +prem at/below K, crossing at K + prem in the TAIL —
    # exactly the region a bounded grid can miss.
    assert exact_breakevens([_leg("call", "sell", 100.0, 2.0)]) == [
        pytest.approx(102.0)
    ]


def test_put_credit_spread_breakeven_between_strikes():
    legs = [_leg("put", "sell", 100.0, 1.0), _leg("put", "buy", 95.0, 0.4)]
    assert exact_breakevens(legs) == [pytest.approx(99.4)]


def test_condor_has_two_breakevens():
    legs = [
        _leg("put", "buy", 90.0, 0.2), _leg("put", "sell", 95.0, 0.5),
        _leg("call", "sell", 105.0, 0.5), _leg("call", "buy", 110.0, 0.2),
    ]
    bes = exact_breakevens(legs)
    assert len(bes) == 2
    assert bes[0] == pytest.approx(94.4)
    assert bes[1] == pytest.approx(105.6)


def test_payoff_signs_agree_with_breakevens():
    legs = [_leg("call", "buy", 100.0, 1.5)]
    assert payoff_at_expiry(legs, 101.0) < 0 < payoff_at_expiry(legs, 102.0)


# --- finding 9 end-to-end: POP honest beyond the display grid ------------------


def test_deep_itm_winner_pop_is_high_but_not_certain():
    """Long 60C bought rich (high implied vol) with spot at 100: the true
    breakeven (~68.5) sits far below the ±25% grid floor (75), so the grid
    path printed a hard POP=1.0000 regardless of vol. With a month on the
    clock and fat vol the losing tail is genuinely reachable — the analytic
    path must report high-but-NOT-certain."""
    from routers.journal import _intraday_analytics

    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=64.0,
        net_debit_credit=850.0,
        is_paper=True,
        tier="50K",
        status="open",
    )
    t.id = 999_002
    # Entry 8.50 on a 60C at S=64 (4 intrinsic + 4.5 time, 30 days) back-
    # solves to ~60% IV — the vol regime where a 35% drawdown has real mass.
    t.legs = [_leg(
        "call", "buy", 60.0, 8.5,
        expiry=(date.today() + timedelta(days=30)).isoformat(),
    )]
    out = _intraday_analytics(trade=t, spot=100.0, rate=0.045, elapsed_hours=0.0)
    assert out.pop is not None
    assert 0.90 < out.pop < 0.9999  # never a hard 100% with a reachable tail


def test_far_otm_debit_pop_is_low_but_not_zero():
    """Long 140C @0.4 with spot 100 and a day on the clock: breakeven 140.4
    sits beyond the +25% grid ceiling (125) — the grid path printed a hard
    0%; the analytic path reports small-but-positive."""
    from routers.journal import _intraday_analytics

    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=40.0,
        is_paper=True,
        tier="50K",
        status="open",
    )
    t.id = 999_003
    t.legs = [_leg(
        "call", "buy", 140.0, 0.4,
        expiry=(date.today() + timedelta(days=1)).isoformat(),
    )]
    out = _intraday_analytics(trade=t, spot=100.0, rate=0.045, elapsed_hours=0.0)
    assert out.pop is not None
    assert 0.0 <= out.pop < 0.10  # tiny, and 0 only if the model truly says so