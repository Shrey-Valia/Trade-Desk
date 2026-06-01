"""Ticker search endpoint — partial-match lookup with 0DTE-availability.

Returns a small ranked list of matches given a partial query. Each
match carries a `has_0dte_today` flag so the frontend can badge
0DTE-eligible tickers in the search results.

Phase 1 swapped the hardcoded 16-symbol catalog out for the live
Alpaca universe (~13,000 active US equities + ETFs).

Phase 2 swapped the hardcoded `symbol in zero_dte_universe` flag
out for a live chain-availability check against Alpaca's option
contracts endpoint. Cached 5 minutes per symbol; bulk-fetched in
parallel across the search results.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services import symbol_catalog
from services.chain_availability import has_zero_dte_bulk

router = APIRouter(prefix="/api/ticker", tags=["ticker"])


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
    if not q.strip():
        return TickerSearchResponse(query=q, results=[])

    matches = symbol_catalog.search(q, limit=limit)
    # Live 0DTE flag — bulk-fan-out so a 10-result query doesn't
    # serialize the underlying network calls. has_zero_dte_bulk
    # honors a per-symbol cache, so rapid typing stays fast.
    zdte = has_zero_dte_bulk([e.symbol for e in matches])
    return TickerSearchResponse(
        query=q,
        results=[
            SearchHit(
                symbol=e.symbol,
                name=e.name,
                has_0dte_today=bool(zdte.get(e.symbol, False)),
            )
            for e in matches
        ],
    )
