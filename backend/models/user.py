"""User accounts — the multi-user prop-firm shell.

Each user owns up to 5 combines (paid evaluation accounts); the one in
`active_combine_id` drives the trading terminal header and is the
combine new trades bind to.

`active_combine_id` is a plain Integer rather than a ForeignKey:
users↔combines would be circular, and SQLite cannot ALTER TABLE ADD
CONSTRAINT, so the usual use_alter escape hatch doesn't exist. Every
read path validates ownership through the combines table instead.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stored lowercased + stripped; unique doubles as the login index.
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_combine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Copy trading: the combine whose trades are mirrored to this user's
    # follower combines (those with combine.copy_follow=True). None = copy
    # trading off. Plain Integer for the same circular-FK reason as above.
    copy_lead_combine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Per-tier Daily Loss Limit overrides as JSON {tier: dollars}. Empty {}
    # means use each tier's default DLL. Enforced server-side in
    # combine_state (clamped to the 1-10%-of-starting-balance band).
    dll_overrides_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}"
    )
    # Per-tier DLL DISABLE flags as a JSON list of tier keys, e.g. ["50K"].
    # When a tier is listed the Daily Loss Limit is switched OFF for that
    # tier's combines — matching real Topstep, which dropped the DLL in 2024.
    # With the DLL off the auto-liquidation + soft-gate skip the DLL branch
    # entirely; the MLL floor still binds. Empty [] = DLL on everywhere.
    dll_disabled_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )

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

    @property
    def dll_overrides(self) -> dict[str, float]:
        try:
            return {k: float(v) for k, v in json.loads(self.dll_overrides_json or "{}").items()}
        except (ValueError, TypeError, AttributeError):
            return {}

    @dll_overrides.setter
    def dll_overrides(self, value: dict[str, float]) -> None:
        self.dll_overrides_json = json.dumps(value)

    @property
    def dll_disabled(self) -> list[str]:
        """Tier keys with the Daily Loss Limit switched OFF."""
        try:
            raw = json.loads(self.dll_disabled_json or "[]")
            return [str(t) for t in raw] if isinstance(raw, list) else []
        except (ValueError, TypeError, AttributeError):
            return []

    @dll_disabled.setter
    def dll_disabled(self, value: list[str]) -> None:
        self.dll_disabled_json = json.dumps(list(dict.fromkeys(value)))

    def dll_enabled_for(self, tier: str) -> bool:
        """Whether the Daily Loss Limit is active for this tier (default on)."""
        return tier not in self.dll_disabled
