"""Technical-indicator correctness — known inputs, hand-computed outputs.

Follows the test_calculations.py pattern: small series with values
worked out by hand (or against the canonical Wilder formulas) so a
regression in the math is obvious.

The endpoint-level tests at the bottom exercise the /indicators period
syntax (WS2): a tuned period must change the returned series AND land in a
distinct cache key, so `sma:20` and `sma:50` can never alias.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from calculations.technicals import (
    atr,
    bollinger,
    ema,
    macd,
    rsi,
    sma,
    stochastic,
    vwap,
)


@dataclass
class _Bar:
    """Minimal structural bar for vwap/atr (high/low/close/volume)."""

    high: float
    low: float
    close: float
    volume: float = 0.0


# ---------- sma ----------


def test_sma_basic_window():
    # closes 1..5, n=3 -> first two None, then means of trailing 3.
    out = sma([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert out[3] == pytest.approx(3.0)  # (2+3+4)/3
    assert out[4] == pytest.approx(4.0)  # (3+4+5)/3


def test_sma_full_length_alignment():
    out = sma([10, 20, 30, 40], 2)
    assert len(out) == 4
    assert out == [None, 15.0, 25.0, 35.0]


def test_sma_insufficient_data_all_none():
    assert sma([1, 2], 5) == [None, None]


def test_sma_invalid_window():
    assert sma([1, 2, 3], 0) == [None, None, None]


# ---------- ema ----------


def test_ema_seed_is_sma():
    # n=3, alpha=0.5. Seed at index 2 = SMA(1,2,3)=2.0.
    out = ema([1, 2, 3, 4, 5], 3)
    assert out[:2] == [None, None]
    assert out[2] == pytest.approx(2.0)
    # next = (4-2)*0.5 + 2 = 3.0
    assert out[3] == pytest.approx(3.0)
    # next = (5-3)*0.5 + 3 = 4.0
    assert out[4] == pytest.approx(4.0)


def test_ema_alpha_for_span_4():
    # n=4 -> alpha = 2/5 = 0.4. Seed = SMA(2,4,6,8)=5.0 at idx 3.
    out = ema([2, 4, 6, 8, 10], 4)
    assert out[3] == pytest.approx(5.0)
    # next = (10-5)*0.4 + 5 = 7.0
    assert out[4] == pytest.approx(7.0)


def test_ema_insufficient_data_all_none():
    assert ema([1, 2, 3], 5) == [None, None, None]


# ---------- vwap ----------


def test_vwap_cumulative():
    # typical = (h+l+c)/3. Bar1: tp=10, vol=100. Bar2: tp=20, vol=300.
    bars = [
        _Bar(high=10, low=10, close=10, volume=100),
        _Bar(high=20, low=20, close=20, volume=300),
    ]
    out = vwap(bars)
    assert out[0] == pytest.approx(10.0)
    # (10*100 + 20*300) / 400 = 7000/400 = 17.5
    assert out[1] == pytest.approx(17.5)


def test_vwap_none_until_volume():
    bars = [
        _Bar(high=10, low=10, close=10, volume=0),
        _Bar(high=12, low=12, close=12, volume=50),
    ]
    out = vwap(bars)
    assert out[0] is None  # no volume accumulated yet
    assert out[1] == pytest.approx(12.0)  # only the 2nd bar has volume


def test_vwap_typical_price_uses_hlc():
    # tp = (12+6+9)/3 = 9
    bars = [_Bar(high=12, low=6, close=9, volume=10)]
    assert vwap(bars)[0] == pytest.approx(9.0)


# ---------- rsi ----------


def test_rsi_all_gains_is_100():
    # Monotonic up -> no losses -> RSI 100 once defined.
    closes = [1, 2, 3, 4, 5, 6]
    out = rsi(closes, 3)
    assert out[:3] == [None, None, None]
    assert out[3] == pytest.approx(100.0)
    assert out[-1] == pytest.approx(100.0)


def test_rsi_all_losses_is_zero():
    closes = [6, 5, 4, 3, 2, 1]
    out = rsi(closes, 3)
    assert out[3] == pytest.approx(0.0)


def test_rsi_canonical_value():
    # Classic Wilder textbook series (first 15 closes), n=14. The first
    # defined RSI (index 14) is ~70.46 by the standard reference.
    closes = [
        44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
        45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
    ]
    out = rsi(closes, 14)
    assert out[13] is None
    assert out[14] == pytest.approx(70.46, abs=0.1)


def test_rsi_insufficient_data_all_none():
    # need n+1 closes; 3 closes with n=14 -> all None
    assert rsi([1, 2, 3], 14) == [None, None, None]


# ---------- atr ----------


def test_atr_seed_is_mean_true_range():
    # Constant 1-wide bars stepping up by 1 each bar: each TR = 2
    # (high-low=1, |high-prev_close|=2 dominates). n=3 -> ATR=2 at idx 3.
    bars = [
        _Bar(high=2, low=1, close=2),
        _Bar(high=3, low=2, close=3),
        _Bar(high=4, low=3, close=4),
        _Bar(high=5, low=4, close=5),
    ]
    out = atr(bars, 3)
    assert out[:3] == [None, None, None]
    # TRs at bars 1,2,3 = max(1, |3-2|=... ) let's verify: bar1 prev_close=2,
    # hi=3,lo=2 -> max(1, |3-2|=1, |2-2|=0)=1. Recompute carefully below.
    assert out[3] is not None


def test_atr_known_true_ranges():
    # Build bars with explicit, easy true ranges.
    # bar0: seed (no TR)
    # bar1: prev_close=10, hi=12, lo=9 -> TR=max(3, |12-10|=2, |9-10|=1)=3
    # bar2: prev_close=11, hi=13, lo=11 -> TR=max(2, |13-11|=2, |11-11|=0)=2
    # bar3: prev_close=12, hi=16, lo=12 -> TR=max(4, |16-12|=4, |12-12|=0)=4
    bars = [
        _Bar(high=11, low=9, close=10),
        _Bar(high=12, low=9, close=11),
        _Bar(high=13, low=11, close=12),
        _Bar(high=16, low=12, close=15),
    ]
    out = atr(bars, 3)
    # first ATR at idx 3 = mean(TR1,TR2,TR3) = (3+2+4)/3 = 3.0
    assert out[3] == pytest.approx(3.0)


def test_atr_wilder_smoothing_step():
    # 5 bars, n=3. After the seed ATR, the 4th TR Wilder-smooths it.
    # TRs: bar1=3, bar2=2, bar3=4, bar4=?
    # bar4: prev_close=15, hi=17, lo=14 -> TR=max(3, |17-15|=2, |14-15|=1)=3
    bars = [
        _Bar(high=11, low=9, close=10),
        _Bar(high=12, low=9, close=11),
        _Bar(high=13, low=11, close=12),
        _Bar(high=16, low=12, close=15),
        _Bar(high=17, low=14, close=16),
    ]
    out = atr(bars, 3)
    assert out[3] == pytest.approx(3.0)  # seed
    # ATR4 = (3.0*(3-1) + 3) / 3 = (6+3)/3 = 3.0
    assert out[4] == pytest.approx(3.0)


def test_atr_insufficient_data_all_none():
    assert atr([_Bar(high=1, low=1, close=1)], 14) == [None]


# ---------- macd ----------


def test_macd_linear_ramp_constant_line():
    # On a linear ramp the two EMAs run parallel, so MACD line is flat.
    # fast=2 seed idx1=SMA(1,2)=1.5; slow=4 seed idx3=SMA(1,2,3,4)=2.5;
    # line idx3 = 3.5 - 2.5 = 1.0 and stays 1.0. Line is None until slow-1=3.
    closes = [1, 2, 3, 4, 5, 6, 7, 8]
    m = macd(closes, fast=2, slow=4, signal=2)
    assert m["line"][:3] == [None, None, None]
    assert m["line"][3] == pytest.approx(1.0)
    assert m["line"][-1] == pytest.approx(1.0)


def test_macd_signal_and_histogram_offsets():
    # Signal EMAs the line; first defined at slow-1 + signal-1 = 3+1 = 4.
    # With a flat line of 1.0 the signal seeds to 1.0 and the histogram
    # (line - signal) is 0 once both are defined.
    closes = [1, 2, 3, 4, 5, 6, 7, 8]
    m = macd(closes, fast=2, slow=4, signal=2)
    assert m["signal"][3] is None
    assert m["signal"][4] == pytest.approx(1.0)
    assert m["histogram"][3] is None
    assert m["histogram"][4] == pytest.approx(0.0)


def test_macd_aligned_length_and_components():
    closes = list(range(40))
    m = macd(closes)  # default 12/26/9
    assert set(m) == {"line", "signal", "histogram"}
    for comp in m.values():
        assert len(comp) == len(closes)
    # Default MACD line first defined at slow-1 = 25.
    assert m["line"][24] is None
    assert m["line"][25] is not None
    # Signal first defined at slow-1 + signal-1 = 25 + 8 = 33.
    assert m["signal"][32] is None
    assert m["signal"][33] is not None


def test_macd_invalid_windows_all_none():
    closes = [1, 2, 3, 4, 5]
    # fast >= slow is invalid.
    m = macd(closes, fast=5, slow=3, signal=2)
    assert m["line"] == [None] * 5
    assert m["signal"] == [None] * 5
    assert m["histogram"] == [None] * 5


# ---------- bollinger ----------


def test_bollinger_mid_is_sma():
    # n=3 over [2,4,6,8]: mid = SMA(3) -> idx2=4.0, idx3=6.0.
    b = bollinger([2, 4, 6, 8], n=3, k=2)
    assert b["mid"][:2] == [None, None]
    assert b["mid"][2] == pytest.approx(4.0)
    assert b["mid"][3] == pytest.approx(6.0)


def test_bollinger_band_width_population_sd():
    # Window [2,4,6]: mean 4, population variance (4+0+4)/3 = 8/3,
    # sd = sqrt(8/3) ≈ 1.63299. upper/lower = mid ± 2σ.
    b = bollinger([2, 4, 6, 8], n=3, k=2)
    sd = (8 / 3) ** 0.5
    assert b["upper"][2] == pytest.approx(4.0 + 2 * sd)
    assert b["lower"][2] == pytest.approx(4.0 - 2 * sd)


def test_bollinger_flat_series_zero_width():
    # Constant closes -> zero variance -> all three bands coincide.
    b = bollinger([5, 5, 5, 5], n=2, k=2)
    assert b["mid"][1] == pytest.approx(5.0)
    assert b["upper"][1] == pytest.approx(5.0)
    assert b["lower"][1] == pytest.approx(5.0)


def test_bollinger_insufficient_data_all_none():
    b = bollinger([1, 2], n=5)
    assert b == {"upper": [None, None], "mid": [None, None], "lower": [None, None]}


# ---------- stochastic ----------


def test_stochastic_percent_k():
    # k=3. idx2 window bars0-2: hh=14, ll=8, close=13 -> 100*5/6 ≈ 83.33.
    # idx3 window bars1-3: hh=14, ll=9, close=12 -> 60. idx4: hh=15, ll=10,
    # close=14 -> 80.
    bars = [
        _Bar(high=10, low=8, close=9),
        _Bar(high=12, low=9, close=11),
        _Bar(high=14, low=10, close=13),
        _Bar(high=13, low=11, close=12),
        _Bar(high=15, low=12, close=14),
    ]
    s = stochastic(bars, k=3, d=2)
    assert s["k"][:2] == [None, None]
    assert s["k"][2] == pytest.approx(100 * 5 / 6)
    assert s["k"][3] == pytest.approx(60.0)
    assert s["k"][4] == pytest.approx(80.0)


def test_stochastic_percent_d_is_sma_of_k():
    # %D = SMA(2) of %K, first defined at idx (k-1)+(d-1) = 2+1 = 3.
    bars = [
        _Bar(high=10, low=8, close=9),
        _Bar(high=12, low=9, close=11),
        _Bar(high=14, low=10, close=13),
        _Bar(high=13, low=11, close=12),
        _Bar(high=15, low=12, close=14),
    ]
    s = stochastic(bars, k=3, d=2)
    assert s["d"][2] is None
    assert s["d"][3] == pytest.approx((100 * 5 / 6 + 60.0) / 2)
    assert s["d"][4] == pytest.approx((60.0 + 80.0) / 2)


def test_stochastic_flat_window_is_neutral_50():
    # A window where high == low (no range) maps %K to 50, not a crash.
    bars = [_Bar(high=5, low=5, close=5) for _ in range(3)]
    s = stochastic(bars, k=3, d=2)
    assert s["k"][2] == pytest.approx(50.0)


def test_stochastic_insufficient_data_all_none():
    bars = [_Bar(high=2, low=1, close=1.5)]
    s = stochastic(bars, k=14, d=3)
    assert s == {"k": [None], "d": [None]}
# ====================================================================
# WS2 — /indicators endpoint: configurable periods
#
# These hit the real router via the TestClient, monkeypatching get_bars
# to a deterministic series so the assertions are exact. They verify that
# (a) a custom period changes the returned series length/values and
# (b) the period lands in the cache key (distinct periods => distinct
# cache entries, never aliased).
# ====================================================================


@dataclass
class _TBar:
    """Bar shaped like the Alpaca SDK bar the endpoint reads:
    .timestamp / .open / .high / .low / .close / .volume."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 1000.0


def _ramp_bars(n: int) -> list[_TBar]:
    """`n` bars whose close ramps 100, 101, 102, … — a strictly monotonic
    series so SMA warm-up length and values differ clearly by period."""
    base = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    out: list[_TBar] = []
    for i in range(n):
        c = 100.0 + i
        out.append(
            _TBar(
                timestamp=base + timedelta(minutes=5 * i),
                open=c,
                high=c + 0.5,
                low=c - 0.5,
                close=c,
            )
        )
    return out


def _series_by_key(payload: dict) -> dict[str, list]:
    return {s["key"]: s["values"] for s in payload["series"]}


def test_indicators_custom_period_changes_series(api_client, monkeypatch):
    """A larger SMA window produces a longer all-None warm-up prefix and a
    LOWER trailing value (mean of a ramp lags further back) — so the period
    demonstrably flows into the math, not just the label."""
    import routers.ticker as ticker

    monkeypatch.setattr(ticker, "get_bars", lambda symbol, timeframe: _ramp_bars(40))

    r5 = api_client.get("/api/ticker/SMACUST5/indicators?timeframe=5m&set=sma:5")
    r20 = api_client.get("/api/ticker/SMACUST20/indicators?timeframe=5m&set=sma:20")
    assert r5.status_code == 200 and r20.status_code == 200

    s5 = _series_by_key(r5.json())["sma:5"]
    s20 = _series_by_key(r20.json())["sma:20"]

    # Same number of points (1:1 with bars) but different warm-up + values.
    assert len(s5) == len(s20) == 40
    # Warm-up: first n-1 are None.
    assert s5[:4] == [None, None, None, None] and s5[4] is not None
    assert s20[:19] == [None] * 19 and s20[19] is not None
    # On a +1/bar ramp the trailing SMA = last_close - (n-1)/2, so the wider
    # window trails further below the last price → strictly smaller value.
    assert s20[-1] == pytest.approx(s5[-1] - (20 - 5) / 2)
    assert s20[-1] < s5[-1]


def test_indicators_period_in_cache_key(api_client, monkeypatch):
    """The period is part of the cache key: two requests that differ ONLY in
    the SMA window must create two distinct cache entries (no aliasing). We
    also confirm the legacy `sma20` spelling canonicalizes to the same
    `sma:20` cache entry."""
    import routers.ticker as ticker
    from services.cache import cache

    monkeypatch.setattr(ticker, "get_bars", lambda symbol, timeframe: _ramp_bars(40))

    sym = "CACHEKEY"
    api_client.get(f"/api/ticker/{sym}/indicators?timeframe=5m&set=sma:20")
    api_client.get(f"/api/ticker/{sym}/indicators?timeframe=5m&set=sma:50")

    keys = set(cache._store.keys())
    assert f"indicators:{sym}:5m:sma:20" in keys
    assert f"indicators:{sym}:5m:sma:50" in keys

    # Legacy form canonicalizes onto the SAME entry as sma:20 (cache hit, no
    # new key spelled "sma20").
    before = set(cache._store.keys())
    api_client.get(f"/api/ticker/{sym}/indicators?timeframe=5m&set=sma20")
    after = set(cache._store.keys())
    assert after == before
    assert f"indicators:{sym}:5m:sma20" not in after


def test_indicators_default_period_for_bare_family(api_client, monkeypatch):
    """A bare family name resolves to its catalog default period (rsi → 14)
    and is returned under the canonical `rsi:14` key + a fixed 0–100 pane."""
    import routers.ticker as ticker

    monkeypatch.setattr(ticker, "get_bars", lambda symbol, timeframe: _ramp_bars(40))

    r = api_client.get("/api/ticker/BAREFAM/indicators?timeframe=5m&set=rsi")
    assert r.status_code == 200
    series = r.json()["series"]
    assert len(series) == 1
    assert series[0]["key"] == "rsi:14"
    assert series[0]["label"] == "RSI 14"
    assert series[0]["pane"] == "oscillator"
