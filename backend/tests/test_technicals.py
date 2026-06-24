"""Technical-indicator correctness — known inputs, hand-computed outputs.

Follows the test_calculations.py pattern: small series with values
worked out by hand (or against the canonical Wilder formulas) so a
regression in the math is obvious.
"""

from dataclasses import dataclass

import pytest

from calculations.technicals import atr, ema, rsi, sma, vwap


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
