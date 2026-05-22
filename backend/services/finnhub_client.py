"""Finnhub client with TTL caching + per-call spacing.

Free tier is 60 calls/min. The watchlist refresh cycle issues ~31 calls;
we space them ~0.3s apart so a single tick can't burst into the limit
even if APScheduler fires slightly off-cadence.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import finnhub
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config import settings
from services.cache import cache

# Use ET (market time) for any "today" decisions — UTC midnight is hours
# before US market close and would silently drop today's earnings rows
# from an evening refresh.
_ET = ZoneInfo("America/New_York")

log = logging.getLogger(__name__)

CALL_SPACING_SECONDS = 0.3


class _NewsItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    datetime: int = Field(alias="datetime")
    headline: str
    source: str = ""
    url: str = ""
    summary: str = ""


class _EarningsRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    date: str
    hour: str = ""  # "amc" / "bmo" / ""


def _client() -> finnhub.Client:
    return finnhub.Client(api_key=settings.finnhub_api_key)


def _sleep_spacing() -> None:
    time.sleep(CALL_SPACING_SECONDS)


def company_news(symbol: str, lookback_hours: int = 24) -> list[_NewsItem]:
    """Last 24h of company news, parsed + validated."""
    cache_key = f"finnhub:news:{symbol}:{lookback_hours}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=1)
    try:
        raw = _client().company_news(symbol, _from=start.isoformat(), to=today.isoformat())
    except Exception as exc:  # noqa: BLE001
        log.warning("finnhub company_news failed for %s: %s", symbol, exc)
        return []
    finally:
        _sleep_spacing()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    out: list[_NewsItem] = []
    for row in raw or []:
        try:
            item = _NewsItem.model_validate(row)
        except ValidationError:
            continue
        if datetime.fromtimestamp(item.datetime, tz=timezone.utc) >= cutoff:
            out.append(item)

    out.sort(key=lambda i: i.datetime, reverse=True)
    cache.set(cache_key, out, ttl_seconds=55)
    return out


def earnings_calendar(days_forward: int = 5) -> list[_EarningsRow]:
    """One global earnings calendar call covering the next N trading days."""
    cache_key = f"finnhub:earnings:{days_forward}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    today = datetime.now(_ET).date()
    end = today + timedelta(days=days_forward + 2)  # include weekend buffer
    try:
        raw = _client().earnings_calendar(
            _from=today.isoformat(),
            to=end.isoformat(),
            symbol="",
            international=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("finnhub earnings_calendar failed: %s", exc)
        return []
    finally:
        _sleep_spacing()

    rows = (raw or {}).get("earningsCalendar", []) if isinstance(raw, dict) else []
    log.info(
        "finnhub earnings_calendar %s..%s: raw_keys=%s row_count=%d sample=%s",
        today,
        end,
        list(raw.keys()) if isinstance(raw, dict) else type(raw).__name__,
        len(rows),
        rows[:2],
    )

    out: list[_EarningsRow] = []
    rejected = 0
    for row in rows:
        try:
            out.append(_EarningsRow.model_validate(row))
        except ValidationError:
            rejected += 1
            continue
    if rejected:
        log.warning("earnings_calendar: %d rows rejected by schema", rejected)

    cache.set(cache_key, out, ttl_seconds=3600)  # earnings dates rarely change intraday
    return out


def earnings_calendar_for_symbol(
    symbol: str, _from: str, to: str
) -> list[_EarningsRow]:
    """Per-symbol earnings calendar across an arbitrary window. Cached 24h.

    Retries on 429 with a 65s sleep (Finnhub's rate-limit window resets every
    minute). Up to 3 attempts before giving up — used by the backfill where
    losing a ticker means losing 5y of training data.
    """
    cache_key = f"finnhub:earnings_sym:{symbol}:{_from}:{to}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    raw = None
    for attempt in range(3):
        try:
            raw = _client().earnings_calendar(
                _from=_from, to=to, symbol=symbol, international=False
            )
            break
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "429" in msg or "limit" in msg.lower():
                wait = 65
                log.warning(
                    "finnhub earnings_calendar(%s) rate-limited (attempt %d); sleeping %ds",
                    symbol, attempt + 1, wait,
                )
                time.sleep(wait)
                continue
            log.warning("finnhub earnings_calendar(%s) failed: %s", symbol, exc)
            break
        finally:
            _sleep_spacing()

    rows = (raw or {}).get("earningsCalendar", []) if isinstance(raw, dict) else []
    out: list[_EarningsRow] = []
    for r in rows:
        try:
            out.append(_EarningsRow.model_validate(r))
        except ValidationError:
            continue
    cache.set(cache_key, out, ttl_seconds=86400)
    return out


def company_earnings(symbol: str, limit: int = 20) -> list:
    """Historical EPS surprises (one row per quarter). Free-tier may cap below `limit`."""
    cache_key = f"finnhub:company_earnings:{symbol}:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = _client().company_earnings(symbol, limit=limit)
    except Exception as exc:  # noqa: BLE001
        log.warning("finnhub company_earnings failed for %s: %s", symbol, exc)
        return []
    finally:
        _sleep_spacing()
    cache.set(cache_key, raw or [], ttl_seconds=3600)
    return raw or []


def next_earnings_for(symbol: str, days_forward: int = 30) -> str | None:
    """ISO date string of the symbol's next earnings within the window, or None.

    Walks the cached `earnings_calendar()` response — adds zero new API
    calls. Pass `days_forward=30` so the same cached payload serves both
    the watchlist's 5-day filter and the price header's 14-day ER badge.
    """
    rows = earnings_calendar(days_forward=days_forward)
    today = datetime.now(_ET).date()
    upcoming: list = []
    for r in rows:
        if r.symbol != symbol:
            continue
        try:
            d = datetime.fromisoformat(r.date).date()
        except ValueError:
            continue
        if d >= today:
            upcoming.append(d)
    if not upcoming:
        return None
    return min(upcoming).isoformat()


# Finnhub's stock_social_sentiment AND news_sentiment endpoints are paid-tier
# only — both 403 on the free key. company_news on free tier returns articles
# without per-article sentiment scores, so we can't derive a slope from there
# either. Sentiment categories surface a placeholder note until we wire up
# Stocktwits (or another free source) in a later phase.
SENTIMENT_AVAILABLE = False
SENTIMENT_NOTE = "Sentiment unavailable on free tier"
