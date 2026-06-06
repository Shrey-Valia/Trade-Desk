"""Ticker-selection analytics — algorithmic popular feed.

Aggregates `ticker_selections` rows into a "top N most-selected
symbols by user X in the last D days" feed. Dormant for now — the
search modal renders `curated_universe.POPULAR_TICKERS` until there's
enough selection signal to make algorithmic popular interesting.

Once the data lands, swap `routers.user_browse.get_popular()` to
call `get_popular_tickers(...)` and the modal switches over with no
frontend change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models.ticker_selection import TickerSelection


@dataclass(frozen=True)
class PopularTicker:
    symbol: str
    count: int


def get_popular_tickers(
    session: Session,
    *,
    user_id: int = 1,
    limit: int = 8,
    days: int = 30,
) -> list[PopularTicker]:
    """Top `limit` symbols by selection count over the last `days`.

    Single-user product → `user_id=1` is the only meaningful value
    today, but the column is in the schema and the function carries
    the kwarg so the multi-user expansion is a zero-touch swap.

    Empty selection log → empty list. Callers fall back to the
    curated POPULAR_TICKERS list when the feed is empty (the frontend
    doesn't yet call this — see module docstring).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = session.execute(
        select(TickerSelection.symbol, func.count(TickerSelection.id))
        .where(TickerSelection.user_id == user_id)
        .where(TickerSelection.selected_at >= cutoff)
        .group_by(TickerSelection.symbol)
        .order_by(func.count(TickerSelection.id).desc())
        .limit(limit)
    ).all()
    return [PopularTicker(symbol=sym, count=int(cnt)) for sym, cnt in rows]
