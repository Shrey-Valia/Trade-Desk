"""Payout adjudication workflow — the human review queue.

One row per payout request. The MONEY ledger stays in combine_events
(payout_requested debits at request time; payout_denied re-credits); this
table is the WORKFLOW state the review desk operates on:

    requested → under_review → approved | denied | held
    approved → paid  (disbursement stays simulated for now)
    held → approved | denied  (a hold is a parking state, not terminal)
    any non-terminal → cancelled  (lifecycle void: account reset or
    refund/chargeback archival — terminal, never writes a ledger event)

`reason_code` on denial comes from the industry TOS taxonomy
(services/payout_desk.py DENIAL_REASONS). reviewer_id is NULL for the
configurable auto-approve fallback ("system") and the acting admin's user
id otherwise.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime
from services.money import Money

PAYOUT_STATES = (
    "requested",
    "under_review",
    "approved",
    "denied",
    "held",
    "paid",
    "cancelled",
)


class PayoutRequest(Base):
    __tablename__ = "payout_requests"
    __table_args__ = (
        # Queue query: pending states, oldest first; per-combine history.
        Index("ix_payout_requests_state", "state"),
        Index("ix_payout_requests_combine", "combine_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    combine_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("combines.id"), nullable=False
    )
    # Requested dollar amount. Money type: NUMERIC(12,2) on disk (exact cents)
    # — must equal the payout_requested event's amount.
    amount: Mapped[float] = mapped_column(Money, nullable=False)
    # See PAYOUT_STATES above.
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="requested"
    )
    # Denial reason code (services/payout_desk.DENIAL_REASONS key); NULL
    # unless denied.
    reason_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Free-text reviewer note, shown to the trader on denial/hold.
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Admin user id who decided; NULL = the auto-approve fallback.
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
