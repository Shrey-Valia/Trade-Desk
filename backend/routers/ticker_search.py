"""Ticker search endpoint — partial-match lookup with 0DTE-availability.

Returns a small ranked list of matches given a partial query. Each
match carries a `has_0dte_today` flag so the frontend can badge
0DTE-eligible tickers in the search results.

Phase 1 swapped the hardcoded 16-symbol catalog out for the live
Alpaca universe (~10,000+ active US equities + ETFs). The catalog
service handles ranking + fallback; the router stays thin.

The 0DTE flag still uses settings.zero_dte_universe in Phase 1.
Phase 2 replaces it with a live chain-availability check.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from config import settings
from services import symbol_catalog

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
    zero_dte = {s.upper() for s in settings.zero_dte_universe}
    return TickerSearchResponse(
        query=q,
        results=[
            SearchHit(
                symbol=e.symbol,
                name=e.name,
                has_0dte_today=e.symbol in zero_dte,
            )
            for e in matches
        ],
    )
