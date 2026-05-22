"""Trade journal model — Trade Desk Phase 1.

Stores both paper trades and journaled real trades; `is_paper` is the
only distinguisher. Legs are JSON-serialized (one row per trade) since
SQLite has no native list type and the shape varies by strategy. Phase
2 will read these rows back, run them through `calculations.black_scholes`
to render the combined payoff curve, and overlay each trade's strikes
on the price chart.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    # Legs stored as JSON text. Schema enforced at the API boundary via
    # schemas/journal.py; the DB just persists the serialized blob.
    legs_json: Mapped[str] = mapped_column(Text, nullable=False)
    entry_date: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    entry_underlying_price: Mapped[float] = mapped_column(Float, nullable=False)
    net_debit_credit: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open")
    exit_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    exit_underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def legs(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.legs_json or "[]")
        except (ValueError, TypeError):
            return []

    @legs.setter
    def legs(self, value: list[dict[str, Any]]) -> None:
        self.legs_json = json.dumps(value)
