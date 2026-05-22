"""GET /api/market/status — NYSE session state for the dashboard header.

Pulled from pandas_market_calendars (the same source we use for trading-day
gating elsewhere). 60s cache — session boundaries don't move intraday.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
from fastapi import APIRouter
from pydantic import BaseModel

from config import settings
from services.alpaca_client import get_quotes
from services.cache import cache
from services.fred_client import vix_history

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

_NYSE = mcal.get_calendar("NYSE")
_ET = ZoneInfo("America/New_York")

# Pre-market and after-hours windows used to label the status pill.
# (NYSE doesn't formally trade pre/post but the data feed + UI conventions do.)
_PRE_OPEN = (4, 0)     # 04:00 ET
_AFTER_CLOSE = (20, 0)  # 20:00 ET


class MarketStatusResponse(BaseModel):
    status: Literal["open", "closed", "pre", "after"]
    label: str
    next_open: str | None
    next_close: str | None


@router.get("/status", response_model=MarketStatusResponse)
def get_market_status() -> MarketStatusResponse:
    cache_key = "market:status"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(_ET)
    today = now.date()
    # Pull a 7-day window — handles weekends and holidays in one lookup.
    schedule = _NYSE.schedule(start_date=today, end_date=today + timedelta(days=10))

    todays_session = None
    if today in {d.date() for d in schedule.index}:
        row = schedule.loc[schedule.index.normalize() == datetime.combine(today, datetime.min.time())]
        if not row.empty:
            todays_session = (
                row.iloc[0]["market_open"].to_pydatetime(),
                row.iloc[0]["market_close"].to_pydatetime(),
            )

    status: Literal["open", "closed", "pre", "after"]
    label: str
    next_open: str | None = None
    next_close: str | None = None

    if todays_session is not None:
        open_ts, close_ts = todays_session
        if open_ts <= now <= close_ts:
            status, label = "open", "Open"
            next_close = close_ts.astimezone(_ET).isoformat()
        elif now < open_ts and (now.hour, now.minute) >= _PRE_OPEN:
            status, label = "pre", "Pre-market"
            next_open = open_ts.astimezone(_ET).isoformat()
        elif now > close_ts and (now.hour, now.minute) <= _AFTER_CLOSE:
            status, label = "after", "After-hours"
        else:
            status, label = "closed", "Closed"
    else:
        status, label = "closed", "Closed"

    # Find the next session's open if we don't already have one (closed/after).
    if next_open is None:
        for ts in schedule.index:
            session_open = schedule.loc[ts]["market_open"].to_pydatetime()
            if session_open > now:
                next_open = session_open.astimezone(_ET).isoformat()
                break

    response = MarketStatusResponse(
        status=status, label=label, next_open=next_open, next_close=next_close,
    )
    cache.set(cache_key, response, ttl_seconds=60)
    return response


class IndexQuote(BaseModel):
    symbol: str
    price: float
    change_pct: float


class IndicesResponse(BaseModel):
    spy: IndexQuote | None
    qqq: IndexQuote | None
    vix: IndexQuote | None


@router.get("/indices", response_model=IndicesResponse)
def get_indices() -> IndicesResponse:
    """SPY + QQQ from Alpaca quotes, VIX from FRED (Alpaca rejects ^VIX)."""
    cache_key = "market:indices"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    quotes = get_quotes(["SPY", "QQQ"])
    spy = _from_quote(quotes.get("SPY"), "SPY")
    qqq = _from_quote(quotes.get("QQQ"), "QQQ")
    vix = _vix_from_fred()

    response = IndicesResponse(spy=spy, qqq=qqq, vix=vix)
    cache.set(cache_key, response, ttl_seconds=5)
    return response


def _from_quote(quote, symbol: str) -> IndexQuote | None:
    if quote is None:
        return None
    return IndexQuote(symbol=symbol, price=quote.price, change_pct=quote.change_pct)


class LiquidUniverseResponse(BaseModel):
    symbols: list[str]


@router.get("/liquid_universe", response_model=LiquidUniverseResponse)
def get_liquid_universe() -> LiquidUniverseResponse:
    """The prewarmed liquid set — drives Trade Desk symbol autocomplete.

    Single source of truth lives in config.Settings.prewarm_liquid_universe;
    exposing it via the API keeps the frontend autocomplete in sync without
    a manual copy."""
    return LiquidUniverseResponse(symbols=list(settings.prewarm_liquid_universe))


def _vix_from_fred() -> IndexQuote | None:
    today = datetime.now(_ET).date()
    series = vix_history(today - timedelta(days=15), today)
    if not series:
        return None
    sorted_dates = sorted(series)
    latest = series[sorted_dates[-1]]
    prev = series[sorted_dates[-2]] if len(sorted_dates) >= 2 else latest
    change_pct = (latest - prev) / prev * 100 if prev else 0.0
    return IndexQuote(symbol="VIX", price=latest, change_pct=change_pct)
