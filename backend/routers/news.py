"""GET /api/news?symbol=SPY&limit=20 — ticker-scoped headlines.

Thin wrapper over Alpaca's news API via the existing authenticated client
(`services.alpaca_client.get_news`). Responses are cached server-side per
symbol (5 min) to stay well under the free feed's rate limits. On an
Alpaca error / 429 we return 503 (not an empty list) so the frontend can
show a distinct "News unavailable" state.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.alpaca_client import NewsUnavailable, get_news

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


class NewsItem(BaseModel):
    id: str
    headline: str
    summary: str
    source: str
    url: str
    created_at: str


class NewsResponse(BaseModel):
    symbol: str
    items: list[NewsItem]


@router.get("", response_model=NewsResponse)
def get_ticker_news(
    symbol: str = Query(..., min_length=1, max_length=12),
    limit: int = Query(20, ge=1, le=50),
) -> NewsResponse:
    """Recent headlines for one symbol.

    200 with `items: []` means the feed succeeded but the symbol has no
    recent news. A 503 means the upstream feed errored / rate-limited —
    the frontend renders these two cases differently.
    """
    sym = symbol.upper()
    try:
        items = get_news(sym, limit)
    except NewsUnavailable:
        # Distinct from "no news": the frontend keys its error state on this.
        raise HTTPException(status_code=503, detail="News unavailable")
    return NewsResponse(symbol=sym, items=[NewsItem(**it) for it in items])
