"""Payout destinations and tax posture — the money-out prerequisites.

`payout_methods`: where an approved payout would be disbursed. Typed per
rail (ach | wire | crypto) with rail-specific fields in details_json; one
default per user is enforced in the service layer. Disbursement execution
stays a simulated no-op (standing decision) — the row is the destination
the real rail adapter will read when it lands.

`tax_profiles`: one row per user — W-9 (US) or W-8BEN (non-US) declaration
collected before the first payout. Only the TIN's last 4 are retained; the
firm's yearly 1099-NEC aggregation (admin endpoint) sums PAID payouts per
user against the $600 reporting threshold.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime

PAYOUT_METHOD_TYPES = ("ach", "wire", "crypto")
TAX_FORM_TYPES = ("W9", "W8BEN")


class PayoutMethod(Base):
    __tablename__ = "payout_methods"
    __table_args__ = (
        Index("ix_payout_methods_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # "ach" | "wire" | "crypto"
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # User-facing label, e.g. "Chase ****1234".
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    # Rail-specific destination fields as JSON. NEVER logged; masked in API
    # responses except last-4 identifiers.
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class TaxProfile(Base):
    __tablename__ = "tax_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True
    )
    # "W9" | "W8BEN"
    form_type: Mapped[str] = mapped_column(String(8), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    # Mailing address as JSON {line1, line2?, city, region, postal, country}.
    address_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Last 4 of SSN/EIN (W-9) or foreign TIN (W-8BEN). Full TINs are never
    # stored — a real rail (Rise/Deel) owns full tax-doc custody later.
    tin_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
