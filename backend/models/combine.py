"""Combines — paid evaluation-account instances.

A combine is one purchase of a tier (50K/100K/150K): its own name,
Topstep-style account code, its own high-water mark, and its own trade
history (trades.combine_id). A user holds at most 5 non-archived
combines at a time; archiving frees a slot and keeps history.

`status` is a plain VARCHAR + pydantic Literal at the API boundary —
deliberately NOT a SQLAlchemy Enum, which on SQLite emits a CHECK
constraint that would force a table rebuild when `passed`/`failed`
become persisted states later. For now those are computed display
states (realized P&L vs the display-only profit target).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class Combine(Base):
    __tablename__ = "combines"
    __table_args__ = (
        Index("ix_combines_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    tier: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Topstep-style: "{tier}TC-{user_id}-{8 digits}", unique app-wide.
    account_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    # Per-combine high-water mark — seeded to the tier's starting
    # balance at purchase; advanced monotonically by the same frozen
    # update_hwm() the single-account model used.
    hwm: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

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
