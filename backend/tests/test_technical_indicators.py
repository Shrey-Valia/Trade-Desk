"""Validate RSI/MACD math against canonical hand-computed values.

The Wilder-vs-standard-EMA bug is the #1 silent failure in indicator
code. The `test_rsi_wilder_known_series` case will fail loudly if
someone "optimizes" RSI by replacing the recurrence with
pandas.ewm(span=14) — different α produces values that look
reasonable but are systematically off.
"""

import numpy as np
import pytest

from ml.technical_indicators import ema, macd_histogram, rsi_wilder


# ---------------------------------------------------------------------------
# RSI — classical Wilder worked example (period=14)
# ---------------------------------------------------------------------------


def test_rsi_monotone_rising_approaches_100():
    """Strictly increasing prices → all gains, no losses → RSI = 100."""
    closes = np.arange(1.0, 31.0)
    out = rsi_wilder(closes, period=14)
    assert np.isnan(out[:14]).all()
    assert out[14] == pytest.approx(100.0)
    assert out[-1] == pytest.approx(100.0)


def test_rsi_monotone_falling_approaches_zero():
    closes = np.arange(30.0, 0.0, -1.0)
    out = rsi_wilder(closes, period=14)
    assert out[14] == pytest.approx(0.0)
    assert out[-1] == pytest.approx(0.0)


def test_rsi_flat_series_is_50():
    closes = np.full(30, 100.0)
    out = rsi_wilder(closes, period=14)
    # No gains, no losses → our convention returns 50.
    assert out[14] == 50.0


def test_rsi_wilder_known_series():
    """Hand-computed RSI(14) on a small Wilder-style fixture.

    Prices: alternating small gains/losses for 14 days then one bigger move.
    Independently computed value at the first valid index (i=14) and after
    a few smoothed steps. Documented in test so anyone editing the function
    knows what value to expect.
    """
    closes = np.array(
        [
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
            46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45,
        ]
    )
    out = rsi_wilder(closes, period=14)

    # Hand-computed: RSI[14] uses simple-average seeds of gains/losses over
    # closes[1..14] (13 deltas).
    deltas = np.diff(closes[:15])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    expected_avg_gain = np.mean(gains[:14])  # SMA seed at index 14
    expected_avg_loss = np.mean(losses[:14])
    expected_rsi = 100 - 100 / (1 + (expected_avg_gain / expected_avg_loss))

    assert out[14] == pytest.approx(expected_rsi, abs=1e-6)
    # And the recurrence at i=15 — Wilder α = 1/14, NOT 2/15.
    avg_gain_15 = (expected_avg_gain * 13 + max(closes[15] - closes[14], 0)) / 14
    avg_loss_15 = (expected_avg_loss * 13 + max(closes[14] - closes[15], 0)) / 14
    expected_rsi_15 = 100 - 100 / (1 + (avg_gain_15 / avg_loss_15))
    assert out[15] == pytest.approx(expected_rsi_15, abs=1e-6)


def test_rsi_wilder_does_NOT_match_standard_ema():
    """Sanity check that we're NOT silently using α = 2/(n+1)."""
    closes = np.linspace(100, 120, 30) + np.sin(np.linspace(0, 6, 30)) * 5
    wilder_rsi = rsi_wilder(closes, period=14)

    # Compute what standard EMA RSI would give (alpha=2/15) — should be
    # measurably DIFFERENT at later indices on a noisy series.
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    alpha_wrong = 2.0 / 15
    g = np.mean(gains[:14])
    l = np.mean(losses[:14])
    for i in range(14, len(closes) - 1):
        g = alpha_wrong * gains[i] + (1 - alpha_wrong) * g
        l = alpha_wrong * losses[i] + (1 - alpha_wrong) * l
    wrong_rsi_last = 100 - 100 / (1 + g / l) if l else 100.0
    assert abs(wilder_rsi[-1] - wrong_rsi_last) > 0.5, (
        "RSI matches standard-EMA formula — Wilder vs standard mix-up suspected"
    )


# ---------------------------------------------------------------------------
# EMA primitive
# ---------------------------------------------------------------------------


def test_ema_seed_at_period_minus_one_is_sma():
    closes = np.arange(1.0, 21.0)
    out = ema(closes, period=5)
    assert np.isnan(out[:4]).all()
    assert out[4] == pytest.approx(np.mean(closes[:5]))


def test_ema_recurrence_matches_alpha_definition():
    closes = np.array([10.0, 11, 12, 13, 14, 15, 16, 17])
    out = ema(closes, period=4)
    alpha = 2.0 / 5
    expected = float(np.mean(closes[:4]))  # seed at index 3
    for i in range(4, len(closes)):
        expected = alpha * closes[i] + (1 - alpha) * expected
        assert out[i] == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# MACD histogram
# ---------------------------------------------------------------------------


def test_macd_histogram_zero_on_flat_series():
    closes = np.full(100, 100.0)
    h = macd_histogram(closes)
    # After warmup, histogram should be ~0 (both EMAs equal, signal = same).
    assert h[-1] == pytest.approx(0.0, abs=1e-9)


def test_macd_histogram_positive_on_accelerating_uptrend():
    # On a LINEAR uptrend both EMAs equilibrate to the same lag → histogram ≈ 0.
    # On an ACCELERATING series the fast EMA leads → histogram > 0.
    n = 100
    closes = 100 + np.arange(n) ** 1.5 / 30
    h = macd_histogram(closes)
    finite_late = h[~np.isnan(h)][-20:]
    assert (finite_late > 0).all(), (
        f"expected positive histogram during accelerating uptrend, got {finite_late}"
    )


def test_macd_line_positive_on_rising_series():
    """Independent sanity check: fast EMA > slow EMA on a rising series,
    so macd_line itself is positive — without subtracting the signal."""
    from ml.technical_indicators import ema
    closes = np.linspace(100, 200, 100)
    macd_line = ema(closes, 12) - ema(closes, 26)
    finite = macd_line[~np.isnan(macd_line)]
    assert finite[-1] > 0
