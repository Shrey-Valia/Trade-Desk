"""Ticker-selection event log — append-only feed for popular-ticker analytics.

Every time the user picks a ticker out of the search modal (from
starred, from popular, or from a search result), the frontend fires
POST /api/ticker/selection which writes one row here.

This table is the substrate for `services.ticker_analytics.get_popular_tickers`,
which today is dormant (frontend uses a curated `POPULAR_TICKERS`
list) and tomorrow lets us replace the curated list with a real
"most-selected by you in the last 30 days" feed without a schema
change or a frontend ship.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class TickerSelection(Base):
    __tablename__ = "ticker_selections"
    __table_args__ = (
        # Aggregation queries filter on (user_id, selected_at) and
        # group by symbol — the composite index keeps that fast even
        # as the log grows.
        Index("ix_ticker_selections_user_time", "user_id", "selected_at"),
        Index("ix_ticker_selections_symbol", "symbol"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    selected_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
