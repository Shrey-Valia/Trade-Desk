"""Combine lifecycle events — the persisted audit trail of the milestones
that were previously computed on-read and then vanished.

One row per meaningful transition: a combine being FUNDED (eval passed),
FAILED (MLL breach), SETTLED (5pm-PT rollover), RESET (a failed eval
restarted), or a PAYOUT requested. The dashboard live-feed reads these so
"you got funded at 10:32" / "MLL breached" finally have a home.

Deliberately a thin append-only log: `type` is a plain VARCHAR (no Enum →
no SQLite rebuild when new event types appear), `amount` is optional (only
payouts carry one), and rows are never mutated.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class CombineEvent(Base):
    __tablename__ = "combine_events"
    __table_args__ = (
        # The feed query: a user's recent events, newest first.
        Index("ix_combine_events_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    combine_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("combines.id"), nullable=False
    )
    # "funded" | "failed" | "settled" | "reset" | "payout"
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(160), nullable=False)
    # Only payout events carry a dollar amount.
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
