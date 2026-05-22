"""GET /api/regime — deterministic market regime classification.

Rule-based, not ML. The card surfaces this honestly via a "Rule-based,
not ML" sublabel in the UI. Cached 60s — regime doesn't move minute-to-
minute and we don't want every dashboard refresh recomputing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter

from calculations.regime import MarketSnapshot, classify
from ml.sector_map import SECTOR_ETFS
from schemas.regime import RegimeResponse, RegimeSignal
from services.alpaca_client import get_daily_bars_history
from services.cache import cache
from services.fred_client import vix_history

router = APIRouter(prefix="/api", tags=["regime"])
log = logging.getLogger(__name__)


@router.get("/regime", response_model=RegimeResponse)
def get_regime() -> RegimeResponse:
    cache_key = "regime:v1"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    snapshot = _build_snapshot()
    classification = classify(snapshot)

    response = RegimeResponse(
        regime=classification.regime,
        confidence=round(classification.confidence, 3),
        contributing_signals=[
            RegimeSignal(name=s.name, value=round(s.value, 4), rule=s.rule, satisfied=s.satisfied)
            for s in classification.contributing_signals
        ],
        updated_at=datetime.now(timezone.utc),
    )
    cache.set(cache_key, response, ttl_seconds=60)
    return response


def _build_snapshot() -> MarketSnapshot:
    """Compose all inputs from cached price + VIX series."""
    spy_closes = _closes_series("SPY")
    vix_levels = _vix_series()
    sector_returns = _sector_5d_returns()

    vix_level = float(vix_levels.iloc[-1]) if not vix_levels.empty else 17.0
    vix_5d_change = _pct_change(vix_levels, 5)
    spy_20d_return = _pct_change(spy_closes, 20)
    spy_5d_return = _pct_change(spy_closes, 5)

    return MarketSnapshot(
        vix_level=vix_level,
        vix_5d_change_pct=vix_5d_change,
        spy_20d_return_pct=spy_20d_return,
        spy_5d_return_pct=spy_5d_return,
        sector_5d_returns=sector_returns,
        hyg_lqd_ratio=None,  # not pulling HYG/LQD on free tier — would add cost
    )


def _closes_series(symbol: str) -> pd.Series:
    bars = get_daily_bars_history(symbol, years_back=1)
    if not bars:
        return pd.Series(dtype=float)
    return pd.Series(
        {pd.Timestamp(b.timestamp.date()): float(b.close) for b in bars}
    ).sort_index()


def _vix_series() -> pd.Series:
    today = datetime.now().date()
    raw = vix_history(today - timedelta(days=60), today)
    if not raw:
        return pd.Series(dtype=float)
    return pd.Series({pd.Timestamp(k): v for k, v in raw.items()}).sort_index()


def _pct_change(series: pd.Series, n: int) -> float:
    """Percent return over n trading days ending at latest available row."""
    if len(series) < n + 1:
        return 0.0
    latest = series.iloc[-1]
    prior = series.iloc[-(n + 1)]
    if prior == 0:
        return 0.0
    return float((latest - prior) / prior * 100)


def _sector_5d_returns() -> dict[str, float]:
    """5-day returns for each sector ETF; missing ETFs default to 0.0."""
    out: dict[str, float] = {}
    for etf in SECTOR_ETFS:
        if etf in ("SPY", "QQQ"):  # not actual sectors
            continue
        series = _closes_series(etf)
        out[etf] = _pct_change(series, 5)
    return out
