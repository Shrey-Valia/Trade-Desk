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


def _ema_full(closes: Sequence[float], n: int) -> list[float | None]:
    """EMA with an SMA seed (same as :func:`ema`) but exposed for reuse by
    MACD, which needs to chain two EMAs and an EMA-of-an-EMA. Identical
    math to ``ema``; kept separate only so MACD's intent reads clearly."""
    return ema(closes, n)


def macd(
    closes: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict[str, list[float | None]]:
    """Moving Average Convergence/Divergence (Appel).

    Returns three per-bar series aligned 1:1 with ``closes``:
      - ``line``      = EMA(fast) − EMA(slow)
      - ``signal``    = EMA(signal) of the MACD line
      - ``histogram`` = line − signal

    The MACD line is ``None`` until both underlying EMAs are defined
    (index ``slow-1``). The signal line seeds its own EMA from the SMA of
    the first ``signal`` *defined* MACD values, so it first appears at
    index ``slow-1 + signal-1`` (= ``slow + signal - 2``); the histogram
    appears with the signal. Invalid windows (non-positive, fast ≥ slow,
    or not enough data) yield all-``None`` series of the input length.
    """
    length = len(closes)
    none_line: list[float | None] = [None] * length
    if fast <= 0 or slow <= 0 or signal <= 0 or fast >= slow:
        return {"line": none_line[:], "signal": none_line[:], "histogram": none_line[:]}

    fast_ema = _ema_full(closes, fast)
    slow_ema = _ema_full(closes, slow)

    line: list[float | None] = [None] * length
    for i in range(length):
        f = fast_ema[i]
        s = slow_ema[i]
        if f is not None and s is not None:
            line[i] = f - s

    # EMA the MACD line over its *defined* region. The line is contiguous
    # from the first non-None (index slow-1) onward, so we EMA that
    # contiguous tail and map results back to absolute indices.
    defined_idx = [i for i, v in enumerate(line) if v is not None]
    sig: list[float | None] = [None] * length
    hist: list[float | None] = [None] * length
    if len(defined_idx) >= signal:
        start = defined_idx[0]
        tail = [line[i] for i in defined_idx]  # contiguous, all floats
        sig_tail = ema([float(v) for v in tail], signal)  # type: ignore[arg-type]
        for offset, sv in enumerate(sig_tail):
            if sv is None:
                continue
            abs_i = start + offset
            sig[abs_i] = sv
            li = line[abs_i]
            if li is not None:
                hist[abs_i] = li - sv

    return {"line": line, "signal": sig, "histogram": hist}


def bollinger(
    closes: Sequence[float], n: int = 20, k: float = 2.0
) -> dict[str, list[float | None]]:
    """Bollinger Bands — an SMA midline with bands ``k`` population standard
    deviations above/below.

    Returns three per-bar series aligned 1:1 with ``closes``:
      - ``mid``   = SMA(n)
      - ``upper`` = mid + k·σ
      - ``lower`` = mid − k·σ

    σ is the *population* standard deviation over the same trailing ``n``
    closes that feed the midline (TradingView convention). The first
    ``n-1`` entries are ``None``. Invalid windows yield all-``None``.
    """
    length = len(closes)
    mid: list[float | None] = [None] * length
    upper: list[float | None] = [None] * length
    lower: list[float | None] = [None] * length
    if n <= 0 or length < n:
        return {"upper": upper, "mid": mid, "lower": lower}

    for i in range(n - 1, length):
        window = closes[i - n + 1 : i + 1]
        m = sum(window) / n
        var = sum((x - m) ** 2 for x in window) / n  # population variance
        sd = var**0.5
        mid[i] = m
        upper[i] = m + k * sd
        lower[i] = m - k * sd
    return {"upper": upper, "mid": mid, "lower": lower}


def stochastic(
    bars: Sequence[Bar], k: int = 14, d: int = 3
) -> dict[str, list[float | None]]:
    """Stochastic oscillator (%K / %D), 0–100.

    %K_i = 100·(close_i − lowest_low) / (highest_high − lowest_low) over
    the trailing ``k`` bars; %D is the ``d``-period SMA of %K. A flat
    window (high == low) yields %K = 50 (neutral) rather than a divide-by-
    zero. %K first appears at index ``k-1``; %D at index ``k-1 + d-1``.
    Invalid windows yield all-``None`` series of the input length.
    """
    length = len(bars)
    pk: list[float | None] = [None] * length
    pd: list[float | None] = [None] * length
    if k <= 0 or d <= 0 or length < k:
        return {"k": pk, "d": pd}

    for i in range(k - 1, length):
        window = bars[i - k + 1 : i + 1]
        hh = max(b.high for b in window)
        ll = min(b.low for b in window)
        rng = hh - ll
        if rng == 0:
            pk[i] = 50.0
        else:
            pk[i] = 100.0 * (bars[i].close - ll) / rng

    # %D = SMA(d) of the *defined* %K tail (contiguous from index k-1).
    defined = [v for v in pk if v is not None]
    if len(defined) >= d:
        start = k - 1
        d_tail = sma([float(v) for v in defined], d)  # type: ignore[arg-type]
        for offset, dv in enumerate(d_tail):
            if dv is not None:
                pd[start + offset] = dv

    return {"k": pk, "d": pd}
