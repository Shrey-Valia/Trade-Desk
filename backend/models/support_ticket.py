"""Support tickets — the minimum viable trader → operator channel.

A trader whose combine was wrongly failed or whose payout is stuck needs a
route to a human. One row per ticket; the admin queue works it. The reply
loop is deliberately thin (admin_note + a notification to the trader) —
a real helpdesk (Intercom/Zendesk) can replace it without touching the
trader-facing form.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime

TICKET_CATEGORIES = ("rule_dispute", "billing", "payout", "bug", "other")
TICKET_STATUSES = ("open", "replied", "closed")


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        Index("ix_support_tickets_user", "user_id"),
        Index("ix_support_tickets_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # See TICKET_CATEGORIES.
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Auto-attached account context at creation (active combine id/tier/state)
    # so the reviewer doesn't hunt for it.
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # "open" | "replied" | "closed"
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")
    # The operator's reply/resolution note, surfaced to the trader.
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
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
