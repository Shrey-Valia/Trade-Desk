"""Daily-snapshot table for options chains. Schema per README §8.

Populated by `jobs/collect_options_chain.py` every weekday after close.
The dataset accumulates over time; ML training (Phase 6+) and IV-Rank
history both depend on it.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class OptionsSnapshot(Base):
    __tablename__ = "options_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    strike: Mapped[float] = mapped_column(Float, nullable=False)
    expiry: Mapped[date] = mapped_column(Date, nullable=False)
    option_type: Mapped[str] = mapped_column(String(4), nullable=False)  # "call" / "put"
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_options_snapshots_symbol_date", "symbol", "snapshot_date"),
    )
