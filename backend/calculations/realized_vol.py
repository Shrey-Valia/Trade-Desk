"""Annualized realized volatility from a series of closes."""

from __future__ import annotations

import math
from collections.abc import Sequence

TRADING_DAYS_PER_YEAR = 252


def realized_vol(closes: Sequence[float], window: int = 30) -> float | None:
    """Annualized RV (%) computed from log returns over the trailing `window`.

    Returns None when fewer than `window + 1` closes are supplied (need
    at least window+1 prices to get window returns).
    """
    if len(closes) < window + 1:
        return None
    tail = closes[-(window + 1):]
    log_returns = [math.log(tail[i] / tail[i - 1]) for i in range(1, len(tail))]
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    daily_std = math.sqrt(variance)
    return daily_std * math.sqrt(TRADING_DAYS_PER_YEAR) * 100
