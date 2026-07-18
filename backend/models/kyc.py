"""KYC identity-verification state — gates the first payout.

One row per user (unique user_id), tracking the industry-standard state
machine: unverified (no row) → pending → verified | rejected. The provider
is an adapter: "sim" auto-decides (verified unless the declared country is
on the OFAC blocklist in settings); a real provider (Sumsub/Veriff/Stripe
Identity) later lands as a webhook that moves pending → verified/rejected
without a schema change.

No identity DOCUMENTS are stored — only the declared fields and the
provider's decision. Document custody belongs to the provider.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime

KYC_STATUSES = ("pending", "verified", "rejected")


class KycVerification(Base):
    __tablename__ = "kyc_verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, unique=True
    )
    # "pending" | "verified" | "rejected" ("unverified" = no row).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Adapter that decided: "sim" today; a real provider slug later.
    provider: Mapped[str] = mapped_column(String(24), nullable=False, default="sim")
    provider_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Declared identity fields as JSON {legal_name, dob, country, document_type}.
    submitted_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    reject_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
