"""Payment records for combine purchases.

PLACEHOLDER ECONOMICS: `amount` is NULL and status is
'placeholder_paid' until Stripe lands — pricing is a pending business
decision. The row still exists so every combine traces to a purchase
event, and the Stripe swap becomes "fill amount + real status" rather
than a schema change. 'migration_grant' marks combines created by the
one-time single-user → multi-user backfill.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # Set in the same transaction right after the combine row is
    # flushed (we need its id); nullable to allow that ordering.
    combine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tier: Mapped[str] = mapped_column(String(8), nullable=False)
    # NULL until real pricing exists.
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="placeholder_paid"
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
