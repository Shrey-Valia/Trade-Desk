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

# Enforcement modes for a PERSONAL per-tier DLL override (TopstepX-style).
#   "alert"           — event only; no day-lock, no flatten.
#   "liquidate"       — flatten the open book, but keep trading allowed.
#   "liquidate_block" — flatten + day-lock (today's historical behavior).
# Strength order backs the same-day tighten-only rule:
# liquidate_block > liquidate > alert.
DLL_MODES = ("alert", "liquidate", "liquidate_block")
DLL_MODE_STRENGTH: dict[str, int] = {"alert": 1, "liquidate": 2, "liquidate_block": 3}
DEFAULT_DLL_MODE = "liquidate_block"


def _normalize_override(value: object) -> dict | None:
    """One stored override value → {"amount": float, "mode": str, "set_at": str|None}.

    BACKWARD COMPAT: the legacy shape was a bare float (dollars). It maps to
    mode "liquidate_block" — exactly the pre-modes behavior (budget hit →
    day-lock → flatten) — with no set_at stamp (so it is freely editable)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return {"amount": float(value), "mode": DEFAULT_DLL_MODE, "set_at": None}
    if isinstance(value, dict):
        try:
            amount = float(value["amount"])
        except (KeyError, TypeError, ValueError):
            return None
        mode = value.get("mode", DEFAULT_DLL_MODE)
        if mode not in DLL_MODES:
            mode = DEFAULT_DLL_MODE
        set_at = value.get("set_at")
        return {"amount": amount, "mode": mode, "set_at": str(set_at) if set_at else None}
    return None


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
    # Free evaluation-reset credits. Each monthly rebill banks one (Topstep
    # parity), capped at pricing.RESET_CREDIT_CAP; reset_combine consumes one
    # before charging the reset fee.
    reset_credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

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
    # Personal daily PROFIT target ("protect the green day") as JSON
    # {"amount": dollars, "lock": bool} — or the literal null when unset.
    # Per-USER (not per-tier): when a combine's day P&L (realized + open
    # URPL, same basis as the DLL check) reaches +amount, lock=true →
    # flatten + day-lock until the 5pm-PT reset; lock=false → a
    # once-per-day combine_events entry only.
    profit_target_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="null"
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
    def dll_override_entries(self) -> dict[str, dict]:
        """Per-tier personal DLL overrides, normalized to
        {"amount": float, "mode": "alert"|"liquidate"|"liquidate_block",
        "set_at": iso8601|None}. Legacy bare-float values read as
        liquidate_block (today's behavior) with no stamp."""
        try:
            raw = json.loads(self.dll_overrides_json or "{}")
        except (ValueError, TypeError, AttributeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict] = {}
        for k, v in raw.items():
            entry = _normalize_override(v)
            if entry is not None:
                out[str(k)] = entry
        return out

    @dll_override_entries.setter
    def dll_override_entries(self, value: dict[str, dict]) -> None:
        self.dll_overrides_json = json.dumps(value)

    @property
    def dll_overrides(self) -> dict[str, float]:
        """AMOUNT-only view of the overrides — kept for call sites that only
        need the dollar level (mode-agnostic)."""
        return {k: v["amount"] for k, v in self.dll_override_entries.items()}

    @dll_overrides.setter
    def dll_overrides(self, value: dict[str, float]) -> None:
        # Legacy setter: bare amounts become liquidate_block entries (the
        # pre-modes behavior), unstamped.
        self.dll_overrides_json = json.dumps(
            {
                k: {"amount": float(v), "mode": DEFAULT_DLL_MODE, "set_at": None}
                for k, v in value.items()
            }
        )

    @property
    def profit_target(self) -> dict | None:
        """Personal daily profit target — {"amount": float, "lock": bool} or
        None when unset / unparseable."""
        try:
            raw = json.loads(self.profit_target_json or "null")
        except (ValueError, TypeError, AttributeError):
            return None
        if not isinstance(raw, dict):
            return None
        try:
            amount = float(raw["amount"])
        except (KeyError, TypeError, ValueError):
            return None
        if amount <= 0:
            return None
        return {"amount": amount, "lock": bool(raw.get("lock", False))}

    @profit_target.setter
    def profit_target(self, value: dict | None) -> None:
        self.profit_target_json = json.dumps(
            None
            if value is None
            else {"amount": float(value["amount"]), "lock": bool(value.get("lock", False))}
        )

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
