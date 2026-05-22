"""IV Rank + Volatility Risk Premium."""

from __future__ import annotations

from collections.abc import Iterable


def iv_rank(current_iv30: float, history: Iterable[float]) -> float | None:
    """0-100 score for where current IV sits in its history range.

    Canonical formula (README §10) once we have ≥252 days of history.
    Returns None when history has < 2 distinct points or max == min.
    """
    values = [v for v in history if v is not None]
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    if hi == lo:
        return None
    return 100.0 * (current_iv30 - lo) / (hi - lo)


def iv_percentile(current_iv30: float, history: Iterable[float]) -> float | None:
    """Phase 3 proxy: % of historical IV30 readings strictly below current.

    Used while we accumulate the 252-day window for true IV Rank. Same
    0-100 scale, same field name in the API, so the UI doesn't care.
    """
    values = [v for v in history if v is not None]
    if not values:
        return None
    below = sum(1 for v in values if v < current_iv30)
    return 100.0 * below / len(values)


def vrp(current_iv30: float, realized_vol_30d: float) -> float:
    """Volatility Risk Premium. Positive = premium rich (IV > RV)."""
    return current_iv30 - realized_vol_30d
