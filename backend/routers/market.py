"""GET /api/market/status — NYSE session state for the dashboard header.

Authoritative source: Alpaca's /v2/clock via `get_market_clock()`. Falls
back to pandas_market_calendars only if Alpaca is unavailable. Short
cache (15s) so the open/close edge flips promptly when the session
transitions.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal
from fastapi import APIRouter
from pydantic import BaseModel

from config import settings
from services.alpaca_client import MarketDataUnavailable, get_market_clock, get_quotes
from services.cache import cache
from services.fred_client import vix_history
from services.market_calendar import session_close_et

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

_NYSE = mcal.get_calendar("NYSE")
_ET = ZoneInfo("America/New_York")

# Pre-market and after-hours windows used to label the status pill.
# (NYSE doesn't formally trade pre/post but the data feed + UI conventions do.)
_PRE_OPEN = (4, 0)     # 04:00 ET
_AFTER_CLOSE = (20, 0)  # 20:00 ET

# Standard full-session close. Early-close half-days (~9/yr) end at 13:00 —
# session_close_et() reads the actual close off the NYSE schedule.
_STANDARD_CLOSE = time(16, 0)


class MarketStatusResponse(BaseModel):
    status: Literal["open", "closed", "pre", "after"]
    label: str
    next_open: str | None
    next_close: str | None
    # Today's ACTUAL session close (ISO ET; None on non-trading days) and
    # whether it's an early close — on half-days 0DTE settles at 1pm, so the
    # UI must be able to warn. Frontend contract: exact field names
    # today_close / is_early_close.
    today_close: str | None = None
    is_early_close: bool = False
    # Expiration-day close-out policy window (minutes before the bell the
    # monitor force-flattens 0DTE books; 0 = policy disabled) — served so the
    # UI's auto-close countdown always matches the enforced config.
    expiry_closeout_minutes: float = 10.0


def _now_et() -> datetime:
    """Seam for the wall clock so the pre/after label logic is testable."""
    return datetime.now(_ET)


def _today_session_close() -> datetime | None:
    """Today's actual NYSE close (tz-aware ET) from the calendar — early-close
    aware. None when today isn't a trading day."""
    return session_close_et(_now_et().date().isoformat())


@router.get("/status", response_model=MarketStatusResponse)
def get_market_status() -> MarketStatusResponse:
    """NYSE session state for the dashboard header + open-guards.

    Authoritative path: Alpaca's /v2/clock (is_open + next_open +
    next_close). When the clock says CLOSED we still want a clean
    pre/after-hours label, so we derive that from local ET wall clock —
    Alpaca only tells us "regular session?", not pre vs after.

    Fallback path: pandas_market_calendars (the previous logic). Kicks
    in if Alpaca creds are misconfigured or the clock call errors out
    so the dashboard still renders something sensible.
    """
    cache_key = "market:status"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    clock = get_market_clock()
    if clock is not None:
        response = _status_from_alpaca(clock)
    else:
        log.warning("alpaca clock unavailable; using local calendar fallback")
        response = _status_from_local_calendar()
    # Stamp the ENFORCED close-out window once, here, rather than threading it
    # through every branch constructor — the UI countdown must match config.
    response = response.model_copy(
        update={"expiry_closeout_minutes": float(settings.expiry_closeout_minutes)}
    )
    # 15s TTL so the open/close edge transitions promptly.
    cache.set(cache_key, response, ttl_seconds=15)
    return response


def _status_from_alpaca(clock) -> MarketStatusResponse:
    next_open_iso = clock.next_open.isoformat() if clock.next_open else None
    next_close_iso = clock.next_close.isoformat() if clock.next_close else None
    today_close = _today_session_close()
    today_close_iso = today_close.isoformat() if today_close else None
    early = bool(today_close and today_close.astimezone(_ET).time() < _STANDARD_CLOSE)

    if clock.is_open:
        return MarketStatusResponse(
            status="open", label="Open",
            next_open=next_open_iso, next_close=next_close_iso,
            today_close=today_close_iso, is_early_close=early,
        )

    # Closed per Alpaca. Distinguish pre/after for the header pill using
    # local ET wall clock against the conventional windows. Alpaca's clock
    # doesn't surface this directly.
    now = _now_et()
    h, m = now.hour, now.minute
    if (h, m) >= _PRE_OPEN and (h, m) < (9, 30):
        # Pre-market window, only on a trading day. If today isn't a
        # trading day next_open will be a later date — keep "closed" in
        # that case so the pill doesn't lie.
        if clock.next_open and clock.next_open.date() == now.date():
            return MarketStatusResponse(
                status="pre", label="Pre-market",
                next_open=next_open_iso, next_close=next_close_iso,
                today_close=today_close_iso, is_early_close=early,
            )
    # After-hours runs from the session's ACTUAL close (1pm on half-days,
    # not a hardcoded 4pm) through the conventional 20:00 window.
    if today_close is not None and now >= today_close and (h, m) <= _AFTER_CLOSE:
        # Only if today was a trading day. If the next_open is tomorrow
        # (or later) we just spent a trading day.
        if clock.next_open and clock.next_open.date() > now.date():
            return MarketStatusResponse(
                status="after", label="After-hours",
                next_open=next_open_iso, next_close=next_close_iso,
                today_close=today_close_iso, is_early_close=early,
            )
    return MarketStatusResponse(
        status="closed", label="Closed",
        next_open=next_open_iso, next_close=next_close_iso,
        today_close=today_close_iso, is_early_close=early,
    )


def _status_from_local_calendar() -> MarketStatusResponse:
    """Pre-Alpaca fallback. Kept to avoid hard-failing when the clock
    endpoint can't be reached; behavior matches the previous version."""
    now = datetime.now(_ET)
    today = now.date()
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

    if next_open is None:
        for ts in schedule.index:
            session_open = schedule.loc[ts]["market_open"].to_pydatetime()
            if session_open > now:
                next_open = session_open.astimezone(_ET).isoformat()
                break

    return MarketStatusResponse(
        status=status, label=label, next_open=next_open, next_close=next_close,
    )


class IndexQuote(BaseModel):
    symbol: str
    price: float
    change_pct: float
    # True when the value is a prior-session close (FRED VIXCLS publishes
    # end-of-day with a lag) rather than a live quote — the UI labels it
    # "(prev close)" instead of presenting a stale delta as today's move.
    prev_close_only: bool = False
    as_of: str | None = None


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


@router.get("/zerodte_universe", response_model=LiquidUniverseResponse)
def get_zero_dte_universe() -> LiquidUniverseResponse:
    """The 0DTE-eligible allowlist — drives the Trade Desk symbol search.

    Trade Desk is a 0DTE-only product; only symbols with reliable same-
    day options should be selectable. Source of truth is
    `settings.zero_dte_universe`; edit there to add or drop names."""
    return LiquidUniverseResponse(symbols=list(settings.zero_dte_universe))


def _vix_from_fred() -> IndexQuote | None:
    today = datetime.now(_ET).date()
    series = vix_history(today - timedelta(days=15), today)
    if not series:
        return None
    sorted_dates = sorted(series)
    latest = series[sorted_dates[-1]]
    prev = series[sorted_dates[-2]] if len(sorted_dates) >= 2 else latest
    change_pct = (latest - prev) / prev * 100 if prev else 0.0
    return IndexQuote(
        symbol="VIX",
        price=latest,
        change_pct=change_pct,
        prev_close_only=True,
        as_of=sorted_dates[-1].isoformat() if hasattr(sorted_dates[-1], "isoformat") else str(sorted_dates[-1]),
    )
