"""Point-in-time + feature-builder correctness tests.

The PIT tests are the most important in the codebase: a leak here would
silently produce a model that looks great in CV and is useless in
production.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.features import (
    MIN_PRIOR_EARNINGS,
    PriorEarning,
    _assert_point_in_time,
    build_features,
)

EVENT_DATE = date(2026, 5, 15)
SYMBOL = "TEST"


def _bars(end_inclusive: date, n: int, base: float = 100.0, drift: float = 0.001) -> pd.Series:
    """Generate `n` trading-day closes ending at `end_inclusive` (going backward)."""
    dates = pd.bdate_range(end=end_inclusive, periods=n)
    rng = np.random.default_rng(0)
    log_returns = rng.normal(drift, 0.02, size=n)
    closes = base * np.exp(np.cumsum(log_returns))
    return pd.Series(closes, index=dates)


def _prior_earnings(n: int, end_date: date) -> list[PriorEarning]:
    """Return n quarterly events ending before end_date."""
    out: list[PriorEarning] = []
    d = end_date - timedelta(days=90)
    for i in range(n):
        out.append(
            PriorEarning(
                earnings_date=d,
                abs_move_pct=4.0 + i * 0.5,
                eps_surprise_pct=2.0 + i * 0.3,
            )
        )
        d = d - timedelta(days=90)
    return list(reversed(out))


# ---------------------------------------------------------------------------
# Point-in-time discipline (the critical tests)
# ---------------------------------------------------------------------------


def test_assert_point_in_time_passes_when_strictly_before():
    s = pd.Series([1.0, 2.0], index=pd.bdate_range(end=EVENT_DATE - timedelta(days=1), periods=2))
    _assert_point_in_time(s, EVENT_DATE, "test")


def test_assert_point_in_time_raises_when_equal():
    s = pd.Series([1.0], index=[pd.Timestamp(EVENT_DATE)])
    with pytest.raises(AssertionError, match="point-in-time leak"):
        _assert_point_in_time(s, EVENT_DATE, "test")


def test_assert_point_in_time_raises_when_after():
    s = pd.Series([1.0], index=[pd.Timestamp(EVENT_DATE + timedelta(days=1))])
    with pytest.raises(AssertionError, match="point-in-time leak"):
        _assert_point_in_time(s, EVENT_DATE, "test")


def test_build_features_raises_when_symbol_closes_include_event_date():
    # `closes` deliberately includes the event date — should trigger the guard.
    closes = _bars(EVENT_DATE, 80)
    day_before = EVENT_DATE - timedelta(days=1)
    sector = _bars(day_before, 150)
    vix = _bars(day_before, 150, base=15.0)
    with pytest.raises(AssertionError, match="point-in-time leak"):
        build_features(
            symbol=SYMBOL,
            event_date=EVENT_DATE,
            bmo_amc="bmo",
            symbol_closes=closes,  # contains event_date and beyond — should raise
            sector_closes=sector,
            vix_closes=vix,
            prior_earnings=_prior_earnings(8, EVENT_DATE),
        )


def test_build_features_uses_only_prior_data_when_inputs_clean():
    # Inputs strictly before event_date — should not raise; should return dict.
    end = EVENT_DATE - timedelta(days=1)
    closes = _bars(end, 80)
    sector = _bars(end, 150)
    vix = _bars(end, 150, base=15.0)
    feats = build_features(
        symbol=SYMBOL,
        event_date=EVENT_DATE,
        bmo_amc="amc",
        symbol_closes=closes,
        sector_closes=sector,
        vix_closes=vix,
        prior_earnings=_prior_earnings(8, EVENT_DATE),
    )
    assert feats is not None
    assert "prior_rv_20d" in feats
    assert feats["bmo_amc"] == "amc"


def test_last_4_earnings_excludes_event_itself():
    """If we accidentally include the event-being-predicted in last_4 stats,
    avg_move would change. Here we synthesize 4 prior + the event itself
    in the prior list — the builder must filter to events strictly before."""
    day_before = EVENT_DATE - timedelta(days=1)
    closes = _bars(day_before, 150)
    sector = _bars(day_before, 150)
    vix = _bars(day_before, 150, base=15.0)

    priors = _prior_earnings(4, EVENT_DATE)
    feats_clean = build_features(
        symbol=SYMBOL, event_date=EVENT_DATE, bmo_amc="bmo",
        symbol_closes=closes, sector_closes=sector, vix_closes=vix,
        prior_earnings=priors,
    )

    # Add a "future" event that should be excluded.
    leak = priors + [PriorEarning(earnings_date=EVENT_DATE, abs_move_pct=999.0, eps_surprise_pct=999.0)]
    feats_with_leak = build_features(
        symbol=SYMBOL, event_date=EVENT_DATE, bmo_amc="bmo",
        symbol_closes=closes, sector_closes=sector, vix_closes=vix,
        prior_earnings=leak,
    )

    assert feats_clean is not None
    assert feats_with_leak is not None
    # The 999 must not have leaked into the last-4 stats.
    assert feats_with_leak["avg_last_4_er_abs_move"] == feats_clean["avg_last_4_er_abs_move"]


# ---------------------------------------------------------------------------
# Insufficient-history handling
# ---------------------------------------------------------------------------


def test_returns_none_when_fewer_than_minimum_priors():
    closes = _bars(EVENT_DATE - timedelta(days=120), 80)
    sector = _bars(EVENT_DATE - timedelta(days=200), 150)
    vix = _bars(EVENT_DATE - timedelta(days=200), 150, base=15.0)
    too_few = _prior_earnings(MIN_PRIOR_EARNINGS - 1, EVENT_DATE)
    assert (
        build_features(
            symbol=SYMBOL, event_date=EVENT_DATE, bmo_amc="bmo",
            symbol_closes=closes, sector_closes=sector, vix_closes=vix,
            prior_earnings=too_few,
        )
        is None
    )


# ---------------------------------------------------------------------------
# Feature-value sanity
# ---------------------------------------------------------------------------


def test_avg_last_4_er_abs_move_uses_last_four_only():
    # _prior_earnings assigns moves in iteration order (oldest gets largest),
    # so the chronologically MOST RECENT 4 events have moves 4.0, 4.5, 5.0, 5.5.
    # That's what the builder picks: mean = 4.75.
    day_before = EVENT_DATE - timedelta(days=1)
    closes = _bars(day_before, 150)
    sector = _bars(day_before, 150)
    vix = _bars(day_before, 150, base=15.0)
    feats = build_features(
        symbol=SYMBOL, event_date=EVENT_DATE, bmo_amc="bmo",
        symbol_closes=closes, sector_closes=sector, vix_closes=vix,
        prior_earnings=_prior_earnings(8, EVENT_DATE),
    )
    assert feats is not None
    assert feats["avg_last_4_er_abs_move"] == pytest.approx(4.75, abs=0.01)


def test_day_of_week_categorical():
    # 2026-05-15 is a Friday.
    day_before = EVENT_DATE - timedelta(days=1)
    closes = _bars(day_before, 150)
    sector = _bars(day_before, 150)
    vix = _bars(day_before, 150, base=15.0)
    feats = build_features(
        symbol=SYMBOL, event_date=EVENT_DATE, bmo_amc="amc",
        symbol_closes=closes, sector_closes=sector, vix_closes=vix,
        prior_earnings=_prior_earnings(8, EVENT_DATE),
    )
    assert feats is not None
    assert feats["day_of_week"] == "Fri"
