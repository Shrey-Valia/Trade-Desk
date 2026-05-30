"""Combine-tier account state — Trade Desk Phase: account tiers.

Single-row table that stores which combine tier the user has active
and the per-tier high-water mark used to trail the MLL (Maximum Loss
Limit) drawdown floor.

Tier constants live in ``services.account_tiers`` so the math has one
source of truth; this model only persists state. Backwards-compat is
not a concern — the previous single-$10K paper account is being
replaced wholesale.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class AccountState(Base):
    __tablename__ = "account_state"

    # Single-row table; id is always 1.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # The combine tier the user is currently trading on. One of the
    # keys in services.account_tiers.TIERS (TIER_50K / TIER_100K /
    # TIER_150K). Default fresh installs to the 50K combine.
    active_tier: Mapped[str] = mapped_column(
        String(8), nullable=False, default="50K"
    )

    # Per-tier high-water marks. Tracked separately so switching tiers
    # back and forth preserves each tier's progress independently.
    hwm_50k: Mapped[float] = mapped_column(Float, nullable=False, default=50_000.0)
    hwm_100k: Mapped[float] = mapped_column(Float, nullable=False, default=100_000.0)
    hwm_150k: Mapped[float] = mapped_column(Float, nullable=False, default=150_000.0)

    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def get_hwm(self, tier: str) -> float:
        return {
            "50K": self.hwm_50k,
            "100K": self.hwm_100k,
            "150K": self.hwm_150k,
        }[tier]

    def set_hwm(self, tier: str, value: float) -> None:
        if tier == "50K":
            self.hwm_50k = value
        elif tier == "100K":
            self.hwm_100k = value
        elif tier == "150K":
            self.hwm_150k = value
        else:
            raise ValueError(f"unknown tier: {tier}")
