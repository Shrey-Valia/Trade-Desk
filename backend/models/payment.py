"""Payment records for combine purchases.

SIMULATED economics (paper prop firm — no real money moves), but the
amounts are REAL: a purchase records `amount` = the matrix monthly price
(services/pricing.py) with status 'paid'; activating a funded account on
the activation path records the $149 fee with status 'activation_paid'.
The row exists so every combine traces to a purchase, and the Stripe swap
becomes "amount read back from Checkout" rather than a schema change.
'migration_grant' marks combines created by the one-time single-user →
multi-user backfill (amount NULL).
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
    # Dollar amount (simulated). Set to the matrix price for purchases /
    # activations; NULL only for migration_grant backfill rows.
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    # paid | activation_paid | pending | failed | migration_grant
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="paid"
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
