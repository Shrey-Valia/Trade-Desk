"""Phase 7 LSTM vol-feature pipeline correctness.

The close_T=10000 test is the silent-killer detector for the off-by-one
trap on lookback/target alignment. If close_T leaks into the feature
window, two windows that differ ONLY in close_T will produce different
feature arrays. We assert they don't.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ml.vol_features import (
    DOW_NAMES,
    FORWARD,
    LOOKBACK,
    NUMERIC_FEATURES,
    TRADING_DAYS_PER_YEAR,
    TickerData,
    _assert_no_leak,
    build_ticker_dataframe,
    iter_training_windows,
    rolling_normalizer,
    winsorize_per_ticker,
)


def _synthetic_bars(n: int = 600, base: float = 100.0, seed: int = 0) -> dict[str, pd.Series]:
    """Build n trading-day OHLCV series for a fake ticker."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp("2026-05-15"), periods=n)
    log_returns = rng.normal(0, 0.02, size=n)
    closes = pd.Series(base * np.exp(np.cumsum(log_returns)), index=dates, name="close")
    highs = closes * (1 + rng.uniform(0, 0.01, size=n))
    lows = closes * (1 - rng.uniform(0, 0.01, size=n))
    volumes = pd.Series(rng.integers(1_000_000, 10_000_000, size=n).astype(float), index=dates)
    return {"closes": closes, "highs": highs, "lows": lows, "volumes": volumes}


def _vix_synthetic(closes: pd.Series, base: float = 18.0, seed: int = 0) -> dict[date, float]:
    """Varying VIX (real-world VIX is never constant). Random walk around `base`."""
    rng = np.random.default_rng(seed)
    n = len(closes)
    walk = base + np.cumsum(rng.normal(0, 0.3, size=n))
    walk = np.clip(walk, 8.0, 80.0)  # plausible VIX range
    return {ts.date(): float(v) for ts, v in zip(closes.index, walk)}


# ---------------------------------------------------------------------------
# _assert_no_leak: the boundary checks
# ---------------------------------------------------------------------------


def test_assert_no_leak_passes_strictly_before():
    s = pd.DataFrame({"x": [1, 2]}, index=pd.bdate_range(end="2026-05-14", periods=2))
    _assert_no_leak(s, date(2026, 5, 15))  # all rows < 5/15 → ok


def test_assert_no_leak_raises_when_equal():
    s = pd.DataFrame({"x": [1]}, index=[pd.Timestamp("2026-05-15")])
    with pytest.raises(AssertionError, match="vol-feature leak"):
        _assert_no_leak(s, date(2026, 5, 15))


def test_assert_no_leak_raises_when_after():
    s = pd.DataFrame({"x": [1]}, index=[pd.Timestamp("2026-05-16")])
    with pytest.raises(AssertionError, match="vol-feature leak"):
        _assert_no_leak(s, date(2026, 5, 15))


# ---------------------------------------------------------------------------
# Off-by-one trap: close_T must NEVER appear in the feature window
# ---------------------------------------------------------------------------


def test_close_at_T_does_not_leak_into_features():
    """Set close_T to a wildly different value (10000) and assert the feature
    array for prediction date T is identical to the baseline. If close_T
    leaks into any feature row, the arrays will differ catastrophically."""
    bars = _synthetic_bars(n=400, seed=42)
    closes = bars["closes"].copy()

    # Pick a prediction date deep in the series so we have ROLL_WINDOW history.
    target_idx = 350
    target_date = closes.index[target_idx].date()

    vix = _vix_synthetic(closes)
    td_baseline = build_ticker_dataframe(
        symbol="FAKE",
        closes=closes,
        highs=bars["highs"],
        lows=bars["lows"],
        volumes=bars["volumes"],
        vix_by_date=vix,
    )
    baseline_window = next(
        w for w in iter_training_windows(td_baseline, use_vix=True)
        if w.prediction_date == target_date
    )

    # Now perturb close_T (10000 instead of ~100). If it leaks into features,
    # the LSTM sees a totally different input.
    perturbed_closes = closes.copy()
    perturbed_closes.iloc[target_idx] = 10_000.0
    td_perturbed = build_ticker_dataframe(
        symbol="FAKE",
        closes=perturbed_closes,
        highs=bars["highs"],
        lows=bars["lows"],
        volumes=bars["volumes"],
        vix_by_date=vix,
    )
    perturbed_window = next(
        w for w in iter_training_windows(td_perturbed, use_vix=True)
        if w.prediction_date == target_date
    )

    # The feature arrays MUST be identical — close_T is "future" relative
    # to the lookback window, so perturbing it cannot change features.
    np.testing.assert_array_equal(baseline_window.features, perturbed_window.features)


def test_close_at_T_DOES_change_target():
    """Sanity check on the previous test: the target SHOULD change when
    close_T changes (since target uses r_T = log(close_T / close_{T-1}))."""
    bars = _synthetic_bars(n=400, seed=99)
    closes = bars["closes"].copy()
    target_idx = 350
    target_date = closes.index[target_idx].date()

    vix = _vix_synthetic(closes)
    td_baseline = build_ticker_dataframe(
        "FAKE", closes, bars["highs"], bars["lows"], bars["volumes"], vix
    )
    w_base = next(
        w for w in iter_training_windows(td_baseline, use_vix=True)
        if w.prediction_date == target_date
    )

    perturbed = closes.copy()
    perturbed.iloc[target_idx] = 10_000.0
    td_p = build_ticker_dataframe(
        "FAKE", perturbed, bars["highs"], bars["lows"], bars["volumes"], vix
    )
    w_p = next(
        w for w in iter_training_windows(td_p, use_vix=True)
        if w.prediction_date == target_date
    )

    # Target uses close_T as the numerator of r_T, so perturbing it must
    # move the target. (After winsorization the change may be capped — we
    # check raw target which isn't winsorized.)
    assert w_base.target_raw != w_p.target_raw


# ---------------------------------------------------------------------------
# rolling_normalizer: the 7-day quarantine for target normalization
# ---------------------------------------------------------------------------


def test_rolling_normalizer_no_quarantine_excludes_current_row():
    """quarantine=0 (features): row T's stat must use rows < T."""
    s = pd.Series(
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0],
        index=pd.bdate_range(start="2026-01-01", periods=12),
    )
    mu, _ = rolling_normalizer(s, window=4, quarantine=0)
    # mu at index 5 (value 6) should be mean of rows 1..4 = (2+3+4+5)/4 = 3.5
    # NOT mean of rows 2..5 = 3.5 (those happen to be the same here, so:)
    # The shift(1) means the rolling window operates on the SHIFTED series,
    # so mu.iloc[5] = mean(s.shift(1).iloc[2:6]) = mean(s.iloc[1:5]) = (2+3+4+5)/4 = 3.5
    assert mu.iloc[5] == pytest.approx(3.5)


def test_rolling_normalizer_with_target_quarantine_excludes_recent_targets():
    """quarantine=FORWARD (target): row T's stat must use targets that
    completed realization by T-1, i.e. target dates ≤ T-FORWARD."""
    # Build a series where the last 7 values are huge spikes — simulating
    # historical 7d-RV targets whose realization completed ≥7 days before T.
    # With quarantine=7, those should be EXCLUDED at row T.
    n = 300
    s = pd.Series(np.ones(n), index=pd.bdate_range(start="2026-01-01", periods=n))
    spike_start = n - 8
    s.iloc[spike_start:] = 1000.0  # last 8 values are huge

    mu, _ = rolling_normalizer(s, window=10, quarantine=FORWARD)

    # At the very last row, all 10 normalizer-window rows should be in the
    # quarantine zone or before. shift(1+7)=shift(8) → window sees s.iloc[i-8-9 : i-8+1].
    # For i = n-1 = 299: window = s.iloc[282:292]. Those are the last `1`
    # rows just before the spike (spike_start=292). So mu should be 1.0.
    assert mu.iloc[-1] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Winsorization
# ---------------------------------------------------------------------------


def test_winsorize_caps_at_p99():
    s = pd.Series(list(range(1, 101)) + [1000.0])  # 100 values 1..100 plus one spike
    capped = winsorize_per_ticker(s, q=0.99)
    # p99 of [1..100, 1000] is 100.99 → spike clipped to that
    assert capped.iloc[-1] < 200
    # Lower tail untouched
    assert capped.iloc[0] == 1.0


# ---------------------------------------------------------------------------
# build_ticker_dataframe: shape + target alignment
# ---------------------------------------------------------------------------


def test_dataframe_shape_and_target_at_known_position():
    bars = _synthetic_bars(n=300, seed=1)
    td = build_ticker_dataframe(
        "FAKE", bars["closes"], bars["highs"], bars["lows"], bars["volumes"],
        _vix_synthetic(bars["closes"]),
    )
    expected_cols = (
        ["close", "high", "low", "volume", "log_return", "intraday_range",
         "volume_zscore", "vix_level", "vix_5d_change", "rv_20d"]
        + DOW_NAMES
        + ["target"]
    )
    for c in expected_cols:
        assert c in td.df.columns
    # Last FORWARD-1 rows have NaN target (each is missing at least one
    # forward return). Row N-FORWARD has all 7 returns and IS valid.
    assert td.df["target"].iloc[-(FORWARD - 1):].isna().all()
    assert not pd.isna(td.df["target"].iloc[-FORWARD])
    # Earlier rows where 7 forward returns exist should have a real target
    assert not pd.isna(td.df["target"].iloc[100])


def test_dataframe_drops_vix_when_unavailable():
    bars = _synthetic_bars(n=300, seed=2)
    td = build_ticker_dataframe(
        "FAKE", bars["closes"], bars["highs"], bars["lows"], bars["volumes"],
        vix_by_date=None,
    )
    assert td.df["vix_level"].isna().all()
    assert td.df["vix_5d_change"].isna().all()
    # Non-VIX features still populated
    assert not td.df["log_return"].iloc[10:].isna().all()


# ---------------------------------------------------------------------------
# iter_training_windows: end-to-end shape + counts
# ---------------------------------------------------------------------------


def test_iter_training_windows_produces_correct_shapes():
    bars = _synthetic_bars(n=600, seed=7)
    td = build_ticker_dataframe(
        "FAKE", bars["closes"], bars["highs"], bars["lows"], bars["volumes"],
        _vix_synthetic(bars["closes"]),
    )
    windows = list(iter_training_windows(td, use_vix=True))
    assert len(windows) > 50  # plenty of usable rows
    n_features = len(NUMERIC_FEATURES) + len(DOW_NAMES)  # 6 + 5 = 11
    for w in windows:
        assert w.features.shape == (LOOKBACK, n_features)
        assert isinstance(w.target, float)
        assert isinstance(w.target_raw, float)
        # Normalized target should be a finite scalar
        assert not np.isnan(w.target)
