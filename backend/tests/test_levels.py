"""Support/resistance correctness — crafted swing series, known levels.

Follows the test_technicals.py pattern: small bar series with swing
pivots placed by hand so the cluster prices and the support/resistance
split are obvious.
"""

from dataclasses import dataclass

import pytest

from calculations.levels import (
    Pivot,
    _cluster,
    _swing_pivots,
    support_resistance,
)


@dataclass
class _Bar:
    """Minimal structural bar (high/low/close) for level detection."""

    high: float
    low: float
    close: float


def _flat_bars(closes):
    """Bars whose high == low == close — keeps swing prices exactly the
    close values so hand-computed levels are unambiguous."""
    return [_Bar(high=c, low=c, close=c) for c in closes]


# ---------- swing pivots ----------


def test_swing_pivots_zigzag():
    # Zigzag closes: highs at odd indices, lows at even (interior) indices.
    bars = _flat_bars([100, 120, 80, 121, 79, 120, 80, 100])
    pivots = _swing_pivots(bars, width=1)
    highs = [(p.index, p.price) for p in pivots if p.kind == "high"]
    lows = [(p.index, p.price) for p in pivots if p.kind == "low"]
    assert highs == [(1, 120), (3, 121), (5, 120)]
    assert lows == [(2, 80), (4, 79), (6, 80)]


def test_swing_pivots_skip_edges():
    # The first/last `width` bars can't be centred, so a peak there is not
    # reported. The edge peak 200 at index 0 is skipped; interior pivots
    # are: index 1 (100, a low vs 200/150), index 2 (150, a high vs
    # 100/100), index 3 (100, a low vs 150/120).
    bars = _flat_bars([200, 100, 150, 100, 120])
    pivots = _swing_pivots(bars, width=1)
    assert (0, 200, "high") not in [(p.index, p.price, p.kind) for p in pivots]
    assert (2, 150, "high") in [(p.index, p.price, p.kind) for p in pivots]
    assert (1, 100, "low") in [(p.index, p.price, p.kind) for p in pivots]


def test_swing_pivots_monotonic_has_none():
    bars = _flat_bars(list(range(10)))
    assert _swing_pivots(bars, width=1) == []


# ---------- clustering ----------


def test_cluster_merges_within_tolerance():
    # Three highs within a tight band collapse to one touch-weighted level.
    highs = [Pivot(1, 120, "high"), Pivot(3, 121, "high"), Pivot(5, 120, "high")]
    levels = _cluster(highs, tolerance=120 * 0.05, last_index=5)
    assert len(levels) == 1
    assert levels[0].price == pytest.approx((120 + 121 + 120) / 3)
    assert levels[0].touches == 3
    assert levels[0].last_index == 5


def test_cluster_splits_when_far_apart():
    # 100/100.2 merge (within 0.5); 150 is its own cluster.
    highs = [Pivot(1, 100, "high"), Pivot(2, 100.2, "high"), Pivot(5, 150, "high")]
    levels = _cluster(highs, tolerance=100 * 0.005, last_index=5)
    prices = sorted(round(lv.price, 2) for lv in levels)
    touches = {round(lv.price, 1): lv.touches for lv in levels}
    assert prices == [100.1, 150.0]
    assert touches[100.1] == 2
    assert touches[150.0] == 1


def test_cluster_empty():
    assert _cluster([], tolerance=1.0, last_index=0) == []


# ---------- support_resistance ----------


def test_support_resistance_split_by_last_close():
    # Highs cluster ~120.33 (above last close 100) -> resistance;
    # lows cluster ~79.67 (below) -> support.
    bars = _flat_bars([100, 120, 80, 121, 79, 120, 80, 100])
    support, resistance = support_resistance(
        bars, width=1, cluster_pct=0.05, max_levels=3
    )
    assert support == [pytest.approx(79.67, abs=0.01)]
    assert resistance == [pytest.approx(120.33, abs=0.01)]


def test_support_resistance_ranks_and_caps():
    # Two resistance clusters: one tested 3x (~120) and one tested once
    # (~140). With max_levels=1 only the higher-scoring (more touches)
    # level survives.
    bars = _flat_bars(
        [
            100,
            120, 80, 121, 79, 120, 80,  # 3 highs ~120, 3 lows ~80
            140, 90,                     # 1 high ~140
            100,
        ]
    )
    _support, resistance = support_resistance(
        bars, width=1, cluster_pct=0.03, max_levels=1
    )
    assert len(resistance) == 1
    # The 3-touch ~120 cluster outranks the single ~140 touch.
    assert resistance[0] == pytest.approx(120.33, abs=0.5)


def test_support_resistance_insufficient_bars():
    assert support_resistance(_flat_bars([1, 2]), width=3) == ([], [])


def test_support_resistance_no_pivots():
    # Monotonic ramp -> no swings -> empty levels.
    assert support_resistance(_flat_bars(list(range(10))), width=1) == ([], [])
