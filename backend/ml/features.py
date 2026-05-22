"""V1 feature builder for the CatBoost earnings model.

Point-in-time discipline is enforced by `_assert_point_in_time` — every
input series must have its latest timestamp strictly before the event
date. The feature builder will raise rather than silently leak.

Returns None when there's not enough history to build features (e.g.
fewer than 4 prior earnings, or no sector ETF data). CatBoost handles
NaNs natively for individual missing features, but a None return means
"this event is unscoreable, skip entirely."
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ml.sector_map import sector_etf_for

log = logging.getLogger(__name__)

MIN_PRIOR_EARNINGS = 4  # below this we refuse to score; "Insufficient earnings history"

FEATURE_NAMES = [
    "prior_rv_20d",
    "prior_rv_60d",
    "avg_last_4_er_abs_move",
    "std_last_4_er_abs_move",
    "last_eps_surprise_pct",
    "avg_last_4_eps_surprise_pct",
    "sector_etf_return_5d",
    "vix_level",
    "bmo_amc",       # categorical
    "day_of_week",   # categorical
]

CATEGORICAL_FEATURES = ["bmo_amc", "day_of_week"]


@dataclass
class PriorEarning:
    """Subset of HistoricalEarningsEvent fields needed by the feature builder."""

    earnings_date: date
    abs_move_pct: float
    eps_surprise_pct: float | None


def _assert_point_in_time(series: pd.Series | None, event_date: date, name: str) -> None:
    """Raise if any timestamp in `series` is on or after `event_date`.

    The conservative cutoff is the prior trading day's close — which means
    no series may contain `event_date` itself, even for AMC events. We
    accept the small AMC information loss to make leak detection trivial.
    """
    if series is None or len(series) == 0:
        return
    last = series.index.max()
    if hasattr(last, "date"):
        last = last.date()
    if last >= event_date:
        raise AssertionError(
            f"point-in-time leak in {name}: latest timestamp {last} >= event date {event_date}"
        )


def _last_close_strictly_before(closes: pd.Series, event_date: date) -> float | None:
    """Latest close strictly before event_date, or None if none exist."""
    cutoff = pd.Timestamp(event_date)
    prior = closes[closes.index < cutoff]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def _realized_vol(closes: pd.Series, window: int) -> float | None:
    """Annualized RV from log returns over `window` trading days."""
    if len(closes) < window + 1:
        return None
    tail = closes.iloc[-(window + 1):]
    log_returns = np.log(tail.values[1:] / tail.values[:-1])
    if len(log_returns) < 2:
        return None
    daily_std = float(np.std(log_returns, ddof=1))
    return daily_std * math.sqrt(252) * 100


def build_features(
    *,
    symbol: str,
    event_date: date,
    bmo_amc: str,
    symbol_closes: pd.Series,
    sector_closes: pd.Series | None,
    vix_closes: pd.Series,
    prior_earnings: list[PriorEarning],
) -> dict[str, Any] | None:
    """Build the V1 feature dict for one (symbol, event_date) pair.

    All inputs must already be point-in-time-trimmed (or include data the
    builder will trim itself). The builder asserts no series has a
    timestamp >= event_date — see `_assert_point_in_time`.

    Returns None when fewer than MIN_PRIOR_EARNINGS prior events exist
    for the symbol — caller should skip the row.
    """
    _assert_point_in_time(symbol_closes, event_date, f"{symbol} closes")
    _assert_point_in_time(sector_closes, event_date, f"{symbol} sector closes")
    _assert_point_in_time(vix_closes, event_date, "VIX closes")

    prior_for_symbol = [p for p in prior_earnings if p.earnings_date < event_date]
    if len(prior_for_symbol) < MIN_PRIOR_EARNINGS:
        return None

    cutoff = pd.Timestamp(event_date)
    prior_closes = symbol_closes[symbol_closes.index < cutoff]

    # Realized vol features — proxy for IV30 / IV60 since free-tier Finnhub
    # has no historical IV. RV ≈ IV most of the time; the gap is the VRP.
    rv_20 = _realized_vol(prior_closes, 20)
    rv_60 = _realized_vol(prior_closes, 60)

    # Last-4 earnings stats (sorted ascending; take the most recent 4 strictly
    # before this event).
    last_four = sorted(prior_for_symbol, key=lambda p: p.earnings_date)[-4:]
    moves = [p.abs_move_pct for p in last_four]
    avg_move = float(np.mean(moves))
    std_move = float(np.std(moves, ddof=1)) if len(moves) > 1 else 0.0

    surprises = [p.eps_surprise_pct for p in last_four if p.eps_surprise_pct is not None]
    last_surprise = (
        float(last_four[-1].eps_surprise_pct)
        if last_four and last_four[-1].eps_surprise_pct is not None
        else None
    )
    avg_surprise = float(np.mean(surprises)) if surprises else None

    # Sector ETF 5-day return ending at the prior trading day's close.
    sector_5d_return: float | None = None
    if sector_closes is not None and len(sector_closes) >= 6:
        prior_sector = sector_closes[sector_closes.index < cutoff]
        if len(prior_sector) >= 6:
            tail = prior_sector.iloc[-6:]
            sector_5d_return = float((tail.iloc[-1] - tail.iloc[0]) / tail.iloc[0] * 100)

    # VIX level on prior trading day.
    vix_level = _last_close_strictly_before(vix_closes, event_date)

    # Categorical features
    weekday_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    bmo_amc_clean = (bmo_amc or "").lower()
    if bmo_amc_clean not in ("bmo", "amc"):
        bmo_amc_clean = "unk"

    return {
        "prior_rv_20d": rv_20 if rv_20 is not None else float("nan"),
        "prior_rv_60d": rv_60 if rv_60 is not None else float("nan"),
        "avg_last_4_er_abs_move": avg_move,
        "std_last_4_er_abs_move": std_move,
        "last_eps_surprise_pct": last_surprise if last_surprise is not None else float("nan"),
        "avg_last_4_eps_surprise_pct": avg_surprise if avg_surprise is not None else float("nan"),
        "sector_etf_return_5d": sector_5d_return if sector_5d_return is not None else float("nan"),
        "vix_level": vix_level if vix_level is not None else float("nan"),
        "bmo_amc": bmo_amc_clean,
        "day_of_week": weekday_map.get(event_date.weekday(), "unk"),
    }


def feature_matrix(
    rows: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[str]]:
    """Build the (X, cat_features) tuple CatBoost expects."""
    df = pd.DataFrame(rows, columns=FEATURE_NAMES)
    # CatBoost wants categorical columns as strings, never NaN.
    for c in CATEGORICAL_FEATURES:
        df[c] = df[c].fillna("unk").astype(str)
    return df, CATEGORICAL_FEATURES


def sector_for(symbol: str) -> str | None:
    return sector_etf_for(symbol)
