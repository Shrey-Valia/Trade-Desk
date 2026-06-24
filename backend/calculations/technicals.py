"""Technical-indicator overlays for the price chart.

Pure functions over bar/close sequences. Each returns a list aligned
1:1 with the input bars/closes, padding the warm-up region with ``None``
so the frontend can plot a ``LineSeries`` against the same bar
timestamps without index juggling. Where there is not enough data for a
given window the whole series is ``None`` for that prefix only.

Conventions mirror ``realized_vol.py`` / ``expected_move.py``: plain
Python (no numpy needed for these), explicit insufficient-data guards,
and no surprise mutation of inputs.

``Bar`` here is structural — anything with ``.high`` / ``.low`` /
``.close`` / ``.volume`` attributes (the Alpaca SDK bar) or the typed
shim used in tests both satisfy it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Bar(Protocol):
    """Structural bar — the subset of fields the indicators read."""

    high: float
    low: float
    close: float
    volume: float | int | None


def sma(closes: Sequence[float], n: int) -> list[float | None]:
    """Simple moving average over the trailing ``n`` closes.

    Returns a list the same length as ``closes``; the first ``n-1``
    entries are ``None`` (not enough lookback yet). Empty/invalid ``n``
    yields an all-``None`` series of the input length.
    """
    out: list[float | None] = [None] * len(closes)
    if n <= 0 or len(closes) < n:
        return out
    window_sum = sum(closes[:n])
    out[n - 1] = window_sum / n
    for i in range(n, len(closes)):
        # Rolling sum: drop the bar leaving the window, add the new one.
        window_sum += closes[i] - closes[i - n]
        out[i] = window_sum / n
    return out


def ema(closes: Sequence[float], n: int) -> list[float | None]:
    """Exponential moving average, span ``n`` (alpha = 2/(n+1)).

    Seeded with the SMA of the first ``n`` closes (Wilder/TV convention),
    then recursively smoothed. First ``n-1`` entries are ``None``.
    """
    out: list[float | None] = [None] * len(closes)
    if n <= 0 or len(closes) < n:
        return out
    alpha = 2.0 / (n + 1)
    prev = sum(closes[:n]) / n  # SMA seed
    out[n - 1] = prev
    for i in range(n, len(closes)):
        prev = (closes[i] - prev) * alpha + prev
        out[i] = prev
    return out


def vwap(bars: Sequence[Bar]) -> list[float | None]:
    """Cumulative volume-weighted average price.

    Typical price = (high+low+close)/3, weighted by volume, accumulated
    from the first bar. Bars with zero/None volume still advance the
    series (the running VWAP just doesn't move). Returns ``None`` only
    while no volume has accumulated yet.
    """
    out: list[float | None] = []
    cum_pv = 0.0
    cum_vol = 0.0
    for b in bars:
        vol = float(b.volume or 0)
        typical = (b.high + b.low + b.close) / 3.0
        cum_pv += typical * vol
        cum_vol += vol
        out.append(cum_pv / cum_vol if cum_vol > 0 else None)
    return out


def rsi(closes: Sequence[float], n: int = 14) -> list[float | None]:
    """Wilder's Relative Strength Index (0–100).

    Uses the canonical Wilder smoothing: the first average gain/loss is a
    simple mean over the first ``n`` changes, then each subsequent value
    is ``(prev*(n-1)+current)/n``. The first ``n`` entries are ``None``
    (need ``n`` changes => index ``n`` is the first defined value).
    A zero average loss maps to RSI 100 (no down moves in the window).
    """
    out: list[float | None] = [None] * len(closes)
    if n <= 0 or len(closes) < n + 1:
        return out

    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / n
    avg_loss = losses / n
    out[n] = _rsi_from_avgs(avg_gain, avg_loss)

    for i in range(n + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (n - 1) + gain) / n
        avg_loss = (avg_loss * (n - 1) + loss) / n
        out[i] = _rsi_from_avgs(avg_gain, avg_loss)
    return out


def _rsi_from_avgs(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(bars: Sequence[Bar], n: int = 14) -> list[float | None]:
    """Average True Range via Wilder smoothing.

    True range of bar i = max(high-low, |high-prev_close|,
    |low-prev_close|). The first bar has no prior close, so TR starts at
    index 1; the first ATR is the simple mean of the first ``n`` true
    ranges (=> index ``n`` is the first defined value), then Wilder-
    smoothed. The first ``n`` entries are ``None``.
    """
    out: list[float | None] = [None] * len(bars)
    if n <= 0 or len(bars) < n + 1:
        return out

    trs: list[float] = []
    for i in range(1, len(bars)):
        prev_close = bars[i - 1].close
        hi = bars[i].high
        lo = bars[i].low
        tr = max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))
        trs.append(tr)

    # trs[k] corresponds to bars[k+1]. First ATR = mean of first n TRs,
    # landing on bars index n.
    prev_atr = sum(trs[:n]) / n
    out[n] = prev_atr
    for k in range(n, len(trs)):
        prev_atr = (prev_atr * (n - 1) + trs[k]) / n
        out[k + 1] = prev_atr
    return out
