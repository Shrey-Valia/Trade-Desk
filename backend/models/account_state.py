"""LEGACY single-tenant account state — MIGRATION-ONLY. Do not extend.

Retired by the multi-user shell: live per-account state now lives on
``models.combine`` rows (see ``services.combine_state``). This model
survives for exactly one caller — ``database._backfill_multiuser()`` —
which reads a pre-multi-user database's ``active_tier`` and per-tier
high-water marks during the one-time adoption of legacy trades. No
request path reads or writes it, and fresh installs never seed a row
(seeding was removed with the shell; see the note in ``database.py``).

Delete this model when the legacy backfill is retired, not before.
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
