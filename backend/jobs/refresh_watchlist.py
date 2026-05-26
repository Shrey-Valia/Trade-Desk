"""Periodic job that recomputes the watchlist and writes it to SQLite.

Runs every 60s. The job decides whether to actually do work based on the
NYSE calendar — APScheduler always fires, but outside market hours we
just no-op (and let the previous snapshot stand).

Per-ticker fetches are isolated: one ticker's failure (rate-limit blip,
malformed response, network glitch) is logged and skipped — the rest of
the universe still processes and gets written.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from sqlalchemy import delete

from config import settings
from database import SessionLocal
from jobs.categories import (
    build_earnings,
    build_hot_now,
    build_sentiment,
    build_unusual_options,
)
from models.watchlist_item import WatchlistItem
from services.alpaca_client import get_option_chain_volumes, get_quotes
from services.finnhub_client import (
    SENTIMENT_AVAILABLE,
    company_news,
    earnings_calendar,
)
from services.market_calendar import is_market_open
from services.timeouts import CallTimeout, run_with_timeout

log = logging.getLogger(__name__)

# Budget for one whole refresh tick. APScheduler fires this every 60s;
# we keep the cycle bounded so even a maximally-slow run finishes
# before the next tick wants to start. When budget is exhausted the
# loop stops and we persist whatever was gathered — partial data is
# strictly better than letting the scheduler back up.
_TICK_BUDGET_SECONDS = 45.0
# Per-external-call deadline. Healthy Alpaca/Finnhub calls return in
# well under 2s; 8s catches the long-tail without letting a single
# stalled symbol kill the whole tick.
_PER_CALL_TIMEOUT_SECONDS = 8.0
# The earnings calendar pulls a 30-day window — bigger response, so
# we give it a little more headroom.
_EARNINGS_TIMEOUT_SECONDS = 15.0


def _budget_remaining(started: float) -> float:
    return _TICK_BUDGET_SECONDS - (time.monotonic() - started)


def refresh_watchlist(force: bool = False) -> None:
    if not force and not is_market_open():
        log.debug("market closed; skipping watchlist refresh")
        return

    started = time.monotonic()
    universe = list(settings.watchlist_universe)
    log.info(
        "refreshing watchlist for %d symbols (budget=%.0fs)",
        len(universe), _TICK_BUDGET_SECONDS,
    )

    try:
        quotes = run_with_timeout(
            get_quotes, universe, timeout_s=_PER_CALL_TIMEOUT_SECONDS,
        )
    except CallTimeout:
        log.warning("get_quotes timed out; aborting refresh cycle")
        return
    except Exception:
        log.exception("get_quotes failed; aborting refresh cycle")
        return

    news_by_symbol: dict[str, list] = {}
    for sym in universe:
        if _budget_remaining(started) <= 0:
            log.warning(
                "refresh budget exhausted; %d symbols left in news loop",
                len(universe) - len(news_by_symbol),
            )
            break
        try:
            news_by_symbol[sym] = run_with_timeout(
                company_news, sym, timeout_s=_PER_CALL_TIMEOUT_SECONDS,
            )
        except CallTimeout:
            log.warning("company_news timeout for %s; skipping", sym)
            news_by_symbol[sym] = []
        except Exception:
            log.exception("company_news failed for %s; skipping", sym)
            news_by_symbol[sym] = []

    chain_volumes: dict[str, tuple[int, int]] = {}
    for sym in universe:
        if _budget_remaining(started) <= 0:
            log.warning(
                "refresh budget exhausted; chain-volume loop bailing early",
            )
            break
        try:
            result = run_with_timeout(
                get_option_chain_volumes, sym,
                timeout_s=_PER_CALL_TIMEOUT_SECONDS,
            )
        except CallTimeout:
            log.warning("option chain volumes timeout for %s; skipping", sym)
            continue
        except Exception:
            log.exception("option chain volumes failed for %s; skipping", sym)
            continue
        if result is not None:
            chain_volumes[sym] = result

    try:
        # Fetch a 30-day window so the same cached payload also serves the
        # ticker detail endpoint's "next earnings within 14d" lookup.
        # build_earnings filters to its own 5-day window internally.
        earnings = run_with_timeout(
            earnings_calendar, timeout_s=_EARNINGS_TIMEOUT_SECONDS,
            days_forward=30,
        )
    except CallTimeout:
        log.warning("earnings_calendar timed out; using empty list this tick")
        earnings = []
    except Exception:
        log.exception("earnings_calendar failed; using empty list")
        earnings = []

    # Sentiment: paid endpoint on Finnhub free tier — categories surface a
    # note via the API response instead of fake data.
    sentiment_by_symbol: dict[str, float | None] = (
        {} if not SENTIMENT_AVAILABLE else {sym: None for sym in universe}
    )

    categories = {
        "hot_now": build_hot_now(quotes, news_by_symbol),
        "earnings": build_earnings(quotes, earnings, universe),
        "unusual_options": build_unusual_options(quotes, chain_volumes),
        "sentiment_up": build_sentiment(quotes, sentiment_by_symbol, direction="up"),
        "sentiment_down": build_sentiment(quotes, sentiment_by_symbol, direction="down"),
    }

    _persist(categories)
    log.info(
        "watchlist refreshed: %s",
        {k: len(v) for k, v in categories.items()},
    )


def _persist(categories: dict[str, list]) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.execute(delete(WatchlistItem))
        for category, items in categories.items():
            for item in items:
                session.add(
                    WatchlistItem(
                        category=category,
                        symbol=item["symbol"],
                        rank=item["rank"],
                        price=item["price"],
                        change_pct=item["change_pct"],
                        subtitle=item["subtitle"],
                        metadata_json=item["metadata_json"],
                        created_at=now,
                    )
                )
        session.commit()
