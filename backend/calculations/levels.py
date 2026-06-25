"""Automatic support / resistance levels from price structure.

Pure functions over a bar sequence. The approach mirrors how a human
reads a chart: find local swing pivots (a high with ``w`` lower highs on
each side, a low with ``w`` higher lows on each side), then *cluster*
pivots that sit within a small band of each other into a single level —
a price that's been tested several times is one level, not five. Levels
are ranked by how many swings touched them and how recently, and the top
few of each side are returned.

Conventions match ``technicals.py`` / ``expected_move.py``: plain Python,
explicit insufficient-data guards, no mutation of inputs. ``Bar`` is
structural — anything with ``.high`` / ``.low`` / ``.close`` satisfies it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class Bar(Protocol):
    """Structural bar — the subset of fields level detection reads."""

    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Pivot:
    """A detected swing pivot. ``index`` is the bar it occurred on (used for
    recency); ``price`` is the pivot's extreme; ``kind`` is ``"high"`` or
    ``"low"``."""

    index: int
    price: float
    kind: str


@dataclass
class Level:
    """A clustered support/resistance level."""

    price: float
    touches: int
    last_index: int
    score: float


def _swing_pivots(bars: Sequence[Bar], width: int) -> list[Pivot]:
    """Local swing highs/lows.

    A bar at ``i`` is a swing high when its high is the strict-ish maximum
    of the ``[i-width, i+width]`` window (>= neighbours, > at least one
    side so a flat top still registers once); symmetric for swing lows.
    The first/last ``width`` bars can't be centred, so they're skipped.
    """
    pivots: list[Pivot] = []
    n = len(bars)
    if width <= 0:
        return pivots
    for i in range(width, n - width):
        hi = bars[i].high
        lo = bars[i].low
        window = range(i - width, i + width + 1)

        is_high = all(bars[j].high <= hi for j in window) and any(
            bars[j].high < hi for j in window if j != i
        )
        is_low = all(bars[j].low >= lo for j in window) and any(
            bars[j].low > lo for j in window if j != i
        )
        if is_high:
            pivots.append(Pivot(index=i, price=hi, kind="high"))
        if is_low:
            pivots.append(Pivot(index=i, price=lo, kind="low"))
    return pivots


def _cluster(
    pivots: list[Pivot], tolerance: float, last_index: int
) -> list[Level]:
    """Cluster pivots whose prices fall within ``tolerance`` (absolute
    price units) of the running cluster average into one level.

    Greedy single pass over price-sorted pivots: a pivot joins the current
    cluster while it stays within ``tolerance`` of the cluster's mean,
    otherwise it starts a new cluster. Each level's price is the
    touch-weighted mean of its pivots; its score rewards touch count and
    recency (a level tested last week beats one untested for months)."""
    if not pivots:
        return []
    ordered = sorted(pivots, key=lambda p: p.price)
    levels: list[Level] = []

    cur: list[Pivot] = [ordered[0]]
    cur_sum = ordered[0].price

    def flush(group: list[Pivot]) -> None:
        price = sum(p.price for p in group) / len(group)
        last = max(p.index for p in group)
        touches = len(group)
        # Recency in [0,1]: 1.0 at the most recent bar, decaying linearly
        # to 0 at the start of the series. Guards a single-bar series.
        recency = (last / last_index) if last_index > 0 else 1.0
        score = touches + recency  # touches dominate; recency breaks ties
        levels.append(
            Level(price=price, touches=touches, last_index=last, score=score)
        )

    for p in ordered[1:]:
        cur_mean = cur_sum / len(cur)
        if abs(p.price - cur_mean) <= tolerance:
            cur.append(p)
            cur_sum += p.price
        else:
            flush(cur)
            cur = [p]
            cur_sum = p.price
    flush(cur)
    return levels


def support_resistance(
    bars: Sequence[Bar],
    *,
    width: int = 3,
    cluster_pct: float = 0.005,
    max_levels: int = 3,
) -> tuple[list[float], list[float]]:
    """Auto support/resistance from swing structure.

    Returns ``(support_levels, resistance_levels)`` — short, rounded,
    price-ordered lists relative to the latest close: levels at or below
    the last close are support, levels above are resistance. ``width`` is
    the swing pivot half-window; ``cluster_pct`` is the band (fraction of
    the last close, e.g. 0.005 = ±0.5%) within which nearby pivots merge;
    ``max_levels`` caps each side to the highest-scoring levels.

    Returns two empty lists when there isn't enough structure (fewer than
    ``2*width+1`` bars, or no pivots).
    """
    n = len(bars)
    if n < 2 * width + 1:
        return [], []

    pivots = _swing_pivots(bars, width)
    if not pivots:
        return [], []

    last_close = bars[-1].close
    last_index = n - 1
    tolerance = max(last_close * cluster_pct, 1e-9)

    # Cluster highs and lows separately so a swing high and a swing low at
    # a similar price stay distinguishable as resistance vs support intent,
    # then split the merged set by the last close.
    highs = [p for p in pivots if p.kind == "high"]
    lows = [p for p in pivots if p.kind == "low"]
    levels = _cluster(highs, tolerance, last_index) + _cluster(
        lows, tolerance, last_index
    )

    support = [lv for lv in levels if lv.price <= last_close]
    resistance = [lv for lv in levels if lv.price > last_close]

    def top(levels_in: list[Level]) -> list[float]:
        ranked = sorted(levels_in, key=lambda lv: lv.score, reverse=True)
        chosen = ranked[:max_levels]
        return sorted(round(lv.price, 2) for lv in chosen)

    return top(support), top(resistance)
