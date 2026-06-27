"""Trade journal model — Trade Desk Phase 1.

Stores both paper trades and journaled real trades; `is_paper` is the
only distinguisher. Legs are JSON-serialized (one row per trade) since
SQLite has no native list type and the shape varies by strategy. Phase
2 will read these rows back, run them through `calculations.black_scholes`
to render the combined payoff curve, and overlay each trade's strikes
on the price chart.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime
from services.money import Money


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    # Legs stored as JSON text. Schema enforced at the API boundary via
    # schemas/journal.py; the DB just persists the serialized blob.
    legs_json: Mapped[str] = mapped_column(Text, nullable=False)
    entry_date: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    entry_underlying_price: Mapped[float] = mapped_column(Float, nullable=False)
    # Money columns use the Money type (NUMERIC(12,2) on disk, float in Python).
    # See services/money.py for the boundary decision.
    net_debit_credit: Mapped[float] = mapped_column(Money, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="open")
    exit_date: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    exit_underlying_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Money, nullable=True)
    is_paper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Combine tier this trade was opened on (50K / 100K / 150K).
    # Switching tiers later doesn't reshuffle history — each tier owns
    # its own trade list. Defaults to "50K" for the fresh-install case.
    tier: Mapped[str] = mapped_column(String(8), nullable=False, default="50K")

    # The combine instance this trade belongs to (multi-user shell).
    # Nullable for the additive migration; _backfill_multiuser() maps
    # every legacy row, so post-migration there are no NULLs in
    # practice. Ownership scoping goes trade.combine_id → combines.user_id.
    # `tier` stays as a denormalized convenience.
    combine_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
    )

    # Phase 2 (overnight polish) — metadata enrichment. All fields below
    # are NULLABLE and DEFAULTED so existing trade rows keep working
    # without migration; new trades opt in by filling them.
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    mistake_tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_exit: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    screenshot_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Limit/stop orders + SL/TP brackets (order monitor) ---------------
    # `status` carries the order lifecycle: working (limit/stop placed, not
    # yet filled) → open → closed; or cancelled (working order pulled).
    # order_type describes the ENTRY (market/limit/stop/stop_limit). For a
    # plain limit/stop the OPTION-premium trigger is limit_price. For a
    # stop_limit the order ARMS at stop_price (mark crosses it) then RESTS as a
    # limit at limit_price. stop_loss / take_profit are UNDERLYING price levels
    # (the draggable chart brackets) checked by the monitor; close_reason
    # records what closed the position.
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="market")
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Trailing stop (EXIT) — a dynamic stop on an OPEN position that trails the
    # favorable OPTION mark. trail_amount is an absolute $/share offset;
    # trail_pct is a fractional offset (0.10 = 10%). trail_hwm is the
    # monitor-maintained high-water of the favorable mark the trail hangs off
    # (peak for a long, trough for a short); None until the first tick seeds it.
    trail_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_hwm: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    # OCO (one-cancels-the-other): orders sharing an oco_group are siblings —
    # when one FILLS (working entry) or its position CLOSES on a bracket, the
    # monitor cancels the still-working siblings in the group. None = no pairing.
    oco_group: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    close_reason: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Time-in-force for a WORKING (limit/stop/stop_limit) order. "gtc" rests
    # indefinitely until filled/cancelled (default — preserves legacy behavior);
    # "day" is cancelled by the monitor if it survives unfilled to a later
    # trading session. Moot for market orders (they fill immediately).
    time_in_force: Mapped[str] = mapped_column(String(8), nullable=False, default="gtc")

    # Copy trading: the LEAD trade this row was mirrored from (None for an
    # original trade). Lets a lead close cascade to its follower copies.
    copied_from_trade_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True
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
    def legs(self) -> list[dict[str, Any]]:
        try:
            return json.loads(self.legs_json or "[]")
        except (ValueError, TypeError):
            return []

    @legs.setter
    def legs(self, value: list[dict[str, Any]]) -> None:
        self.legs_json = json.dumps(value)

    @property
    def tags(self) -> list[str]:
        try:
            return json.loads(self.tags_json or "[]")
        except (ValueError, TypeError):
            return []

    @tags.setter
    def tags(self, value: list[str]) -> None:
        self.tags_json = json.dumps(value)

    @property
    def mistake_tags(self) -> list[str]:
        try:
            return json.loads(self.mistake_tags_json or "[]")
        except (ValueError, TypeError):
            return []

    @mistake_tags.setter
    def mistake_tags(self, value: list[str]) -> None:
        self.mistake_tags_json = json.dumps(value)

    @property
    def r_multiple(self) -> float | None:
        """realized_pnl / risk_amount when both are present and risk > 0.
        Returns None for open trades or trades without a risk target —
        downstream UI shows '—' in that case rather than a divide-by-
        zero or a misleadingly large number."""
        if self.risk_amount is None or self.risk_amount <= 0:
            return None
        if self.realized_pnl is None:
            return None
        return float(self.realized_pnl) / float(self.risk_amount)
