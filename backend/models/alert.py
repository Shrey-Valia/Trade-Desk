"""Price / earnings / fill alerts (WS6).

A lightweight per-user trigger list. Three kinds:

  - ``price``    : fires when the underlying crosses a threshold. ``direction``
                   ("above"/"below") + ``threshold`` define the trip line; the
                   evaluator compares the live quote and flips ``status`` to
                   "triggered" the first time the condition holds.
  - ``earnings`` : fires when the symbol has an earnings event within a window
                   (evaluated against the calendar feed; informational).
  - ``fill``     : fires when a working order on the symbol fills.

Alerts are one-shot: once ``status`` flips to "triggered" the row stops being
re-evaluated until the user re-arms (or deletes) it. ``triggered_at`` records
when it tripped so the UI can show "fired 3m ago".

Per-user, cookie-auth scoped (``user_id``), mirroring the user_star pattern so
multi-user isolation is enforced at the query layer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # The evaluator lists a user's active alerts; the index keeps that
        # scan cheap as the table grows.
        Index("ix_alerts_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # price | earnings | fill
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    # For price alerts: the crossing level. Null for earnings/fill kinds.
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    # For price alerts: "above" | "below". Null for other kinds.
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # active | triggered
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Free-text note shown in the toast/list when it fires.
    note: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
