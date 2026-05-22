"""Phase 7.7 MLP trend-feature pipeline correctness.

The close_T=10000 test is the silent-killer detector for the off-by-one
trap on lookback/target alignment. Same pattern as the Phase 7 LSTM
features — perturbing close[T] must not change the feature vector for
prediction date T (but MUST change the target).
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.trend_features import (
    FEATURE_NAMES,
    FORWARD,
    WARMUP_DAYS,
    _assert_no_leak,
    build_ticker_trend_dataframe,
    iter_trend_windows,
)


def _synthetic(n: int = 200, base: float = 100.0, seed: int = 0) -> dict[str, pd.Series]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp("2026-05-15"), periods=n)
    log_returns = rng.normal(0.0005, 0.015, size=n)
    closes = pd.Series(base * np.exp(np.cumsum(log_returns)), index=dates)
    volumes = pd.Series(rng.integers(1_000_000, 10_000_000, size=n).astype(float), index=dates)
    return {"closes": closes, "volumes": volumes}


# ---------------------------------------------------------------------------
# _assert_no_leak basics
# ---------------------------------------------------------------------------


def test_assert_no_leak_passes_strictly_before():
    s = pd.DataFrame({"x": [1, 2]}, index=pd.bdate_range(end="2026-05-14", periods=2))
    _assert_no_leak(s, date(2026, 5, 15), "test")


def test_assert_no_leak_raises_when_equal():
    s = pd.DataFrame({"x": [1]}, index=[pd.Timestamp("2026-05-15")])
    with pytest.raises(AssertionError, match="trend-feature leak"):
        _assert_no_leak(s, date(2026, 5, 15), "test")


# ---------------------------------------------------------------------------
# Off-by-one: close[T] must NOT change feature vector but MUST change target
# ---------------------------------------------------------------------------


def test_close_at_T_does_not_leak_into_features():
    bars = _synthetic(n=200, seed=42)
    closes = bars["closes"].copy()

    target_idx = 150
    target_date = closes.index[target_idx].date()

    td_baseline = build_ticker_trend_dataframe(
        symbol="FAKE",
        closes=closes,
        volumes=bars["volumes"],
        sector_closes=closes * 0.5,  # arbitrary sector series
    )
    baseline_window = next(
        w for w in iter_trend_windows(td_baseline)
        if w.prediction_date == target_date
    )

    perturbed_closes = closes.copy()
    perturbed_closes.iloc[target_idx] = 10_000.0
    td_p = build_ticker_trend_dataframe(
        symbol="FAKE",
        closes=perturbed_closes,
        volumes=bars["volumes"],
        sector_closes=closes * 0.5,
    )
    perturbed_window = next(
        w for w in iter_trend_windows(td_p)
        if w.prediction_date == target_date
    )

    # Feature vectors MUST be identical — close[T] is "future" relative to
    # the lookback used by every feature.
    np.testing.assert_array_equal(baseline_window.features, perturbed_window.features)


def test_close_at_T_DOES_change_target():
    """Sanity counter-test for the previous: target = (close[T+5] > close[T]),
    so perturbing close[T] DOWNWARD (to a tiny value) makes the target = 1
    almost certainly, while perturbing UPWARD (huge value) makes target = 0."""
    bars = _synthetic(n=200, seed=99)
    closes_low = bars["closes"].copy()
    closes_high = bars["closes"].copy()
    target_idx = 150
    target_date = closes_low.index[target_idx].date()
    # Push close[T] very low — close[T+5] should easily exceed it → target=1
    closes_low.iloc[target_idx] = 1.0
    # Push close[T] very high — close[T+5] won't reach it → target=0
    closes_high.iloc[target_idx] = 10_000.0

    sector = bars["closes"] * 0.5
    td_low = build_ticker_trend_dataframe("FAKE", closes_low, bars["volumes"], sector)
    td_high = build_ticker_trend_dataframe("FAKE", closes_high, bars["volumes"], sector)
    w_low = next(w for w in iter_trend_windows(td_low) if w.prediction_date == target_date)
    w_high = next(w for w in iter_trend_windows(td_high) if w.prediction_date == target_date)

    assert w_low.target == 1
    assert w_high.target == 0


# ---------------------------------------------------------------------------
# Target alignment: 5-day forward, NOT 5 calendar days
# ---------------------------------------------------------------------------


def test_target_uses_T_plus_5_trading_days():
    closes = pd.Series(
        [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112],
        index=pd.bdate_range(start="2026-01-05", periods=13),
    )
    volumes = pd.Series([1_000_000] * 13, index=closes.index)
    td = build_ticker_trend_dataframe("FAKE", closes, volumes, None)
    # Row at index 7 (a Wed): close = 107. close[T+5] = closes.iloc[12] = 112.
    # 112 > 107 → target = 1.
    assert td.df["target"].iloc[7] == 1
    # Last FORWARD rows have NaN target.
    assert pd.isna(td.df["target"].iloc[-1])
    # Row at index 7 (12 - 5) should be the last with a valid target. Row
    # at index 8 should be NaN since closes.iloc[13] doesn't exist.
    assert pd.isna(td.df["target"].iloc[8])


# ---------------------------------------------------------------------------
# Feature shape + warmup
# ---------------------------------------------------------------------------


def test_iter_trend_windows_produces_correct_shapes():
    bars = _synthetic(n=300, seed=7)
    td = build_ticker_trend_dataframe(
        "FAKE", bars["closes"], bars["volumes"], bars["closes"] * 0.8
    )
    windows = list(iter_trend_windows(td))
    assert len(windows) > 50
    for w in windows:
        assert w.features.shape == (len(FEATURE_NAMES),)
        assert w.target in (0, 1)
        assert not np.isnan(w.features).any()


def test_no_window_before_warmup():
    """First valid prediction must be at or after WARMUP_DAYS."""
    bars = _synthetic(n=200, seed=3)
    td = build_ticker_trend_dataframe("FAKE", bars["closes"], bars["volumes"], None)
    windows = list(iter_trend_windows(td))
    assert all(w.prediction_date >= bars["closes"].index[WARMUP_DAYS].date() for w in windows)


# ---------------------------------------------------------------------------
# Volume-z normalizer doesn't include vol[T-1] in its own window
# (regression check — Phase 7 LSTM had this exact bug pattern)
# ---------------------------------------------------------------------------


def test_volume_perturbation_at_T_does_not_change_features_at_T():
    """Same shape as the close test but for volume."""
    bars = _synthetic(n=200, seed=13)
    sector = bars["closes"] * 0.5
    target_idx = 150
    target_date = bars["closes"].index[target_idx].date()

    base_td = build_ticker_trend_dataframe("FAKE", bars["closes"], bars["volumes"], sector)
    base_w = next(w for w in iter_trend_windows(base_td) if w.prediction_date == target_date)

    perturbed_vol = bars["volumes"].copy()
    perturbed_vol.iloc[target_idx] = 999_999_999_999.0
    p_td = build_ticker_trend_dataframe("FAKE", bars["closes"], perturbed_vol, sector)
    p_w = next(w for w in iter_trend_windows(p_td) if w.prediction_date == target_date)

    np.testing.assert_array_equal(base_w.features, p_w.features)
