"""Pre-warm chain/chart/metrics caches for the most-clicked watchlist tickers.

The chain-snapshot path is the slow leg of /api/ticker/{symbol}/detail —
~8-15s cold (chain fetch + chunked per-contract volume fetch) vs <500ms
warm. By refreshing the top hot_now + unusual_options names every 60s
during market hours, the cache (5min TTL on the snapshot, 30s on chart
and metrics) stays continuously warm and clicks land instantly.

Scope is deliberately narrow: top 5 from hot_now + top 5 from unusual
options. Pre-warming the full 15-ticker universe would burn through rate
limits without buying much — these are the names a user is overwhelmingly
likely to click next.
"""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import HTTPException
from sqlalchemy import select

from config import settings
from database import SessionLocal
from models.watchlist_item import WatchlistItem
from routers.ticker import get_ticker_chart, get_ticker_metrics
from services.alpaca_client import get_chain_snapshot
from services.market_calendar import is_market_open

log = logging.getLogger(__name__)

_HOT_CATEGORIES: tuple[str, ...] = ("hot_now", "unusual_options")
_PER_CATEGORY_CAP = 5
_MAX_CONCURRENCY = 4
# Budget bumped from 30s for the expanded liquid set (~50 symbols on top
# of the hot subset). Hot tickers warm FIRST inside the budget, so even
# if we time out we never lose coverage on the most-clicked names.
_TIME_BUDGET_SECONDS = 50.0
_CHART_TIMEFRAME = "5D"  # frontend default — matches AnnotatedChart.tsx


def prewarm_hot_tickers(force: bool = False) -> None:
    if not force and not is_market_open():
        log.debug("market closed; skipping prewarm")
        return

    hot = _select_hot_symbols()
    liquid = [s for s in settings.prewarm_liquid_universe if s not in set(hot)]
    symbols = hot + liquid
    if not symbols:
        log.debug("no symbols to prewarm; skipping")
        return

    started = time.monotonic()
    try:
        warmed = asyncio.run(_prewarm_async(symbols))
    except Exception:
        log.exception("prewarm_hot_tickers failed")
        return

    elapsed = time.monotonic() - started
    log.info(
        "prewarmed %d/%d tickers (%d hot + %d liquid) in %.2fs",
        warmed,
        len(symbols),
        len(hot),
        len(liquid),
        elapsed,
    )


def _select_hot_symbols() -> list[str]:
    """Top 5 from each hot category, de-duplicated, preserving order.

    These warm FIRST so the most-clicked names always finish within the
    budget even when the liquid set is partially cold.
    """
    with SessionLocal() as session:
        rows = session.execute(
            select(WatchlistItem.category, WatchlistItem.symbol, WatchlistItem.rank)
            .where(WatchlistItem.category.in_(_HOT_CATEGORIES))
            .order_by(WatchlistItem.category, WatchlistItem.rank)
        ).all()

    per_cat: dict[str, int] = {c: 0 for c in _HOT_CATEGORIES}
    seen: set[str] = set()
    ordered: list[str] = []
    for category, symbol, _rank in rows:
        if per_cat.get(category, _PER_CATEGORY_CAP) >= _PER_CATEGORY_CAP:
            continue
        per_cat[category] += 1
        if symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
    return ordered


async def _prewarm_async(symbols: list[str]) -> int:
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    successes = 0

    async def warm(sym: str) -> None:
        nonlocal successes
        async with sem:
            try:
                await asyncio.to_thread(get_chain_snapshot, sym, True)
            except Exception:
                log.exception("prewarm chain failed for %s", sym)
                return
            await asyncio.to_thread(_warm_chart_and_metrics, sym)
            successes += 1

    try:
        await asyncio.wait_for(
            asyncio.gather(*(warm(s) for s in symbols), return_exceptions=True),
            timeout=_TIME_BUDGET_SECONDS,
        )
    except asyncio.TimeoutError:
        log.warning(
            "prewarm budget %.0fs exceeded — moving on with %d warmed",
            _TIME_BUDGET_SECONDS,
            successes,
        )

    return successes


def _warm_chart_and_metrics(sym: str) -> None:
    """Populate chart + metrics caches (30s TTL each). Per-call isolated."""
    try:
        get_ticker_chart(sym, _CHART_TIMEFRAME)
    except HTTPException as exc:
        log.debug("chart prewarm skipped for %s: %s", sym, exc.detail)
    except Exception:
        log.exception("chart prewarm failed for %s", sym)
    try:
        get_ticker_metrics(sym)
    except HTTPException as exc:
        log.debug("metrics prewarm skipped for %s: %s", sym, exc.detail)
    except Exception:
        log.exception("metrics prewarm failed for %s", sym)
