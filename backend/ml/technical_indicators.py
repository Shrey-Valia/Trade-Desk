"""Manual NumPy implementations of RSI(14) and MACD(12,26,9).

We don't use `ta-lib` (native C library, install friction) or pandas-ta
(extra dep). Both functions are small and well-documented; the canonical-
fixture tests guard against the classic Wilder-vs-standard-EMA bug.

Critical implementation notes:
- RSI uses **Wilder's smoothing** with α = 1/n. Standard EMA uses
  α = 2/(n+1). pandas.ewm(span=14).mean() is the WRONG α — values drift
  ~5-10 RSI points vs Wilder on volatile names.
- EMAs are seeded with SMA over the first n values at index n-1.
  Alternative is seeding with the first value; converges to the same
  series after ~3n steps but starts further off.
"""

from __future__ import annotations

import numpy as np


def rsi_wilder(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's RSI(14). Returns array same length as `closes` with NaN
    until the first computable value at index `period`."""
    n = len(closes)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed: simple average over first `period` gains/losses at index `period`.
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    out[period] = _rsi_from_avg(avg_gain, avg_loss)

    # Wilder's recurrence: α = 1/period (not 2/(period+1) as in standard EMA).
    for i in range(period + 1, n):
        delta_idx = i - 1  # deltas[k] = closes[k+1] - closes[k]
        avg_gain = (avg_gain * (period - 1) + gains[delta_idx]) / period
        avg_loss = (avg_loss * (period - 1) + losses[delta_idx]) / period
        out[i] = _rsi_from_avg(avg_gain, avg_loss)
    return out


def _rsi_from_avg(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Standard EMA with α = 2/(period+1), seeded with SMA at index period-1."""
    n = len(values)
    out = np.full(n, np.nan)
    if n < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = float(np.mean(values[:period]))
    for i in range(period, n):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def macd_histogram(
    closes: np.ndarray, fast: int = 12, slow: int = 26, signal_period: int = 9
) -> np.ndarray:
    """MACD histogram = (EMA_fast − EMA_slow) − signal-EMA-of-that.

    Returns same length as closes. NaN until ~ fast+slow+signal_period rows
    of warmup are available.
    """
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = fast_ema - slow_ema
    # Signal line is EMA of the macd_line; need to handle leading NaNs.
    valid = ~np.isnan(macd_line)
    sig = np.full(len(closes), np.nan)
    if valid.sum() >= signal_period:
        first_valid = np.where(valid)[0][0]
        sig_input = macd_line[first_valid:]
        sig_ema = ema(sig_input, signal_period)
        sig[first_valid:] = sig_ema
    return macd_line - sig
