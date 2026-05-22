"""One row per (ticker, earnings_date). Backfilled by scripts/backfill_earnings.py.

Stores both the raw inputs needed for feature recomputation (closes, eps
surprise) and the realized target (abs_move_pct). Features themselves
are computed from this table + cached price series at training time —
not stored here, because a feature change shouldn't require a re-backfill.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Date, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class HistoricalEarningsEvent(Base):
    __tablename__ = "historical_earnings_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    earnings_date: Mapped[date] = mapped_column(Date, nullable=False)
    bmo_amc: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    prev_close: Mapped[float] = mapped_column(Float, nullable=False)
    realized_close: Mapped[float] = mapped_column(Float, nullable=False)
    abs_move_pct: Mapped[float] = mapped_column(Float, nullable=False)
    eps_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_surprise_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Provenance of the event date itself: "finnhub", "yfinance", or "both".
    # Used for backfill telemetry and as a hint when reconciling diffs.
    date_source: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("symbol", "earnings_date", name="uq_earnings_symbol_date"),
        Index("ix_earnings_symbol_date", "symbol", "earnings_date"),
    )
