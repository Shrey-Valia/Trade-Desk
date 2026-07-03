"""Combines — paid evaluation-account instances.

A combine is one purchase of a tier (50K/100K/150K): its own name,
Topstep-style account code, its own high-water mark, and its own trade
history (trades.combine_id). A user holds at most 5 non-archived
combines at a time; archiving frees a slot and keeps history.

`status` is a plain VARCHAR + pydantic Literal at the API boundary —
deliberately NOT a SQLAlchemy Enum, which on SQLite emits a CHECK
constraint that would force a table rebuild when `passed`/`failed`
become persisted states later. For now those are computed display
states (realized P&L vs the display-only profit target).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime
from services.money import Money


class Combine(Base):
    __tablename__ = "combines"
    __table_args__ = (
        Index("ix_combines_user_status", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    tier: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Topstep-style: "{tier}TC-{user_id}-{8 digits}", unique app-wide.
    account_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    # Per-combine RUNNING high-water mark — seeded to the tier's starting
    # balance at purchase; advanced monotonically intraday by the same
    # frozen update_hwm() the single-account model used. Tracks the day
    # high; drives the SETTLED HWM at settlement, not the MLL floor directly.
    # Dollar account value — Money type (NUMERIC(12,2) on disk, float in Python).
    hwm: Mapped[float] = mapped_column(Money, nullable=False)
    # Per-combine SETTLED high-water mark — the basis of the MLL floor.
    # Advances ONLY at the 5pm-PT settlement (settled = max(settled,
    # running)), so the floor is FIXED intraday and re-baselines UP only.
    settled_hwm: Mapped[float] = mapped_column(Money, nullable=False)
    # Last 5pm-PT settlement. None = never settled (settle on first read).
    last_settled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    # Lifecycle status: "active" | "archived". Orthogonal to `outcome`.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Settlement OUTCOME: "active" | "passed" | "failed". Permanent once
    # passed/failed (a combine breaching its MLL fails for good; one meeting
    # the profit target + min-days + consistency passes). Kept separate from
    # `status` so archiving never erases the outcome.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # When the evaluation passed and the account auto-funded. None until the
    # combine passes; once set, the account is FUNDED and accrues payout.
    funded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Pricing path chosen at purchase, fixed for the combine's life:
    # "activation" (lower monthly + a one-time $149 fee on funding) or
    # "no_activation" (higher monthly, $0 fee). See services/pricing.py.
    pricing_path: Mapped[str] = mapped_column(
        String(16), nullable=False, default="activation"
    )
    # Trader's share of funded-account profit, chosen at purchase: 0.80
    # (80/20, normal) or 0.50 (50/50, −$10/mo). Drives payout_eligible.
    profit_split: Mapped[float] = mapped_column(Float, nullable=False, default=0.80)
    # When the funded account was ACTIVATED (the fee paid via /activate-account
    # — $149 on the activation path, $0 on no-activation). None until activated;
    # payouts are gated on it.
    funded_activated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    # Funded-stage accounting EPOCH, stamped by /activate-account alongside
    # funded_activated_at. From this instant the account re-baselines: only
    # trades opened at/after it count, booked payouts DEBIT the balance, and
    # the running/settled HWM re-seed to the tier start (fresh MLL). None =
    # still on eval accounting (including funded-but-not-yet-activated).
    # Kept separate from funded_activated_at so the additive migration can
    # detect pre-epoch funded rows and re-seed their HWM basis exactly once.
    funded_epoch_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
    )
    # Copy trading: when True, this combine mirrors trades opened on the
    # user's lead combine (user.copy_lead_combine_id). See services/copy_trade.
    copy_follow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Size multiplier applied to the lead's contract count before clamping to
    # this follower's cap (e.g. 0.5×, 1×, 2×). Only meaningful when following.
    copy_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # Per-follower bracket overrides (UNDERLYING price levels). When set, a
    # mirrored open uses these instead of the lead trade's stop_loss/take_profit;
    # None means "inherit the lead's bracket". Only meaningful when following.
    copy_stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    copy_take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Eval restart point. A reset (after a fail) stamps this; the engine then
    # counts only trades opened at/after it toward the eval — so the eval
    # starts fresh while the trade HISTORY is preserved (rows are never deleted).
    eval_reset_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime, nullable=True
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
