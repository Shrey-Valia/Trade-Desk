"""Ticker search endpoint — partial-match lookup with 0DTE-availability.

Returns a small ranked list of matches given a partial query. Each
match carries a `has_0dte_today` flag so the frontend can badge
0DTE-eligible tickers in the search results.

The catalog is a small static map of commonly-searched symbols. The
"has 0DTE today" check uses settings.zero_dte_universe — those are
the tickers that reliably have same-day expiry on Alpaca's free feed.
A future iteration can swap this for a live expiry-availability check
against the chain API.
"""

from __future__ import annotations

from typing import NamedTuple

from fastapi import APIRouter, Query
from pydantic import BaseModel

from config import settings

router = APIRouter(prefix="/api/ticker", tags=["ticker"])


class CatalogEntry(NamedTuple):
    symbol: str
    name: str


# Small curated set — the 0DTE universe plus a handful of commonly
# searched-for tickers. Search is over symbol + name (case-insensitive
# substring); results favor symbol-prefix matches.
_CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry("SPY", "SPDR S&P 500 ETF"),
    CatalogEntry("QQQ", "Invesco QQQ Trust"),
    CatalogEntry("IWM", "iShares Russell 2000 ETF"),
    CatalogEntry("SPX", "S&P 500 Index"),
    CatalogEntry("NDX", "Nasdaq 100 Index"),
    CatalogEntry("DIA", "SPDR Dow Jones Industrial Average ETF"),
    CatalogEntry("AAPL", "Apple Inc."),
    CatalogEntry("MSFT", "Microsoft Corp."),
    CatalogEntry("NVDA", "NVIDIA Corp."),
    CatalogEntry("TSLA", "Tesla Inc."),
    CatalogEntry("AMD", "Advanced Micro Devices"),
    CatalogEntry("GOOGL", "Alphabet Inc."),
    CatalogEntry("AMZN", "Amazon.com Inc."),
    CatalogEntry("META", "Meta Platforms Inc."),
    CatalogEntry("NFLX", "Netflix Inc."),
    CatalogEntry("AVGO", "Broadcom Inc."),
)


class SearchHit(BaseModel):
    symbol: str
    name: str
    has_0dte_today: bool


class TickerSearchResponse(BaseModel):
    query: str
    results: list[SearchHit]


@router.get("/search", response_model=TickerSearchResponse)
def search_tickers(
    q: str = Query("", description="Partial query — symbol or name"),
    limit: int = Query(10, ge=1, le=20),
) -> TickerSearchResponse:
    needle = q.strip().lower()
    if not needle:
        return TickerSearchResponse(query=q, results=[])

    zero_dte = {s.upper() for s in settings.zero_dte_universe}

    # Score: 3 for symbol equality, 2 for symbol-prefix, 1 for symbol
    # substring, 0.5 for name substring. Ties broken by alphabetical.
    scored: list[tuple[float, CatalogEntry]] = []
    for entry in _CATALOG:
        sym_lc = entry.symbol.lower()
        name_lc = entry.name.lower()
        score = 0.0
        if sym_lc == needle:
            score = 3
        elif sym_lc.startswith(needle):
            score = 2
        elif needle in sym_lc:
            score = 1
        elif needle in name_lc:
            score = 0.5
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: (-x[0], x[1].symbol))
    top = scored[:limit]
    return TickerSearchResponse(
        query=q,
        results=[
            SearchHit(
                symbol=e.symbol,
                name=e.name,
                has_0dte_today=e.symbol in zero_dte,
            )
            for _, e in top
        ],
    )
