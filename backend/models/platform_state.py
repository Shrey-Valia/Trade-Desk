"""Platform operational state — a tiny DB-backed key-value store.

Backs the operator kill switch (trading_mode: normal | close_only | halted),
the per-symbol ban list, and small watermarks (e.g. the lifecycle notifier's
last-seen combine_event id). DB-backed so it survives restarts and is
settable even when the market-data feed is the thing that broke; typed
accessors live in services/platform_state.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class PlatformState(Base):
    __tablename__ = "platform_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    # JSON-encoded value (string/number/list/object).
    value_json: Mapped[str] = mapped_column(Text, nullable=False, default="null")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
