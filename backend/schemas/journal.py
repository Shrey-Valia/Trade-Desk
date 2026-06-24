"""API schema for the Trade Desk journal — Phase 1.

Trade leg shape: side (call/put) + action (buy/sell) + strike + expiry +
contracts + entry_price. Phase 2 will feed these into the existing BS
pricer (calculations.black_scholes.Leg) for the payoff curve overlay.
"""

from __future__ import annotations

from datetime import date as DateType, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from calculations.strategies import STRATEGY_TYPES

TradeStatus = Literal["working", "open", "closed", "cancelled"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
CloseReason = Literal["manual", "stop_loss", "take_profit", "expiry", "liquidation", "copy"]
LegSide = Literal["call", "put"]
LegAction = Literal["buy", "sell"]

# How many legs each known strategy is *expected* to have. Used for soft
# validation — a mismatched leg count emits a warning but doesn't reject
# the trade (custom variants are allowed).
EXPECTED_LEG_COUNT: dict[str, int] = {
    "long_call": 1,
    "long_put": 1,
    "short_call": 1,
    "short_put": 1,
    "long_straddle": 2,
    "long_strangle": 2,
    "bull_call_spread": 2,
    "bear_put_spread": 2,
    "bull_put_spread": 2,
    "bear_call_spread": 2,
    "calendar_spread": 2,
    "iron_condor": 4,
}


class TradeLeg(BaseModel):
    side: LegSide
    action: LegAction
    strike: float = Field(gt=0)
    expiry: DateType
    contracts: int = Field(gt=0, default=1)
    entry_price: float = Field(ge=0)        # per-contract premium

    @field_validator("strike")
    @classmethod
    def round_strike(cls, v: float) -> float:
        # Strikes are usually quoted at 0.50 / 1.00 / 2.50 increments; round
        # to a sensible precision so we don't carry 0.000000001 noise.
        return round(v, 2)


# Fixed vocabulary for the post-trade "what did I do wrong" capture.
# Surfaced as the suggestion set in the close-position UI; custom strings
# are also allowed via the `mistake_tags` free list.
MISTAKE_TAG_VOCABULARY: tuple[str, ...] = (
    "chased IV crush",
    "rolled too soon",
    "no exit plan",
    "oversized",
    "revenge trade",
    "ignored regime",
    "held too long",
    "cut winner early",
)


class TradeIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    strategy: str
    legs: list[TradeLeg] = Field(min_length=1)
    entry_date: datetime
    entry_underlying_price: float = Field(gt=0)
    net_debit_credit: float | None = None    # computed from legs if omitted
    is_paper: bool = True
    notes: str | None = None
    # Phase 2 enrichment — all optional and additive.
    tags: list[str] = Field(default_factory=list)
    confidence: int | None = Field(default=None, ge=1, le=5)
    thesis: str | None = None
    planned_exit: str | None = None
    risk_amount: float | None = Field(default=None, gt=0)
    screenshot_url: str | None = None

    @field_validator("symbol")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper().strip()

    @field_validator("strategy")
    @classmethod
    def known_strategy(cls, v: str) -> str:
        # Soft constraint: unknown strategy keys are allowed (the schema is
        # a journaling tool, not a trade-builder) but we normalize case.
        return v.lower().strip()


class TradeUpdate(BaseModel):
    """PATCH payload — every field optional. Pass `status='closed'` plus
    exit_date / exit_underlying_price / realized_pnl to close a trade.
    Notes / mistake tags / review can be edited independently after
    close."""

    status: TradeStatus | None = None
    exit_date: datetime | None = None
    exit_underlying_price: float | None = Field(default=None, gt=0)
    realized_pnl: float | None = None
    notes: str | None = None
    # Self-applied intent tags (planned / good setup / …). Distinct from
    # mistake_tags; editable from the journal day-detail.
    tags: list[str] | None = None
    mistake_tags: list[str] | None = None
    review_note: str | None = None


class BracketsUpdate(BaseModel):
    """PUT payload for SL/TP brackets — underlying price levels. Send BOTH
    each time (PUT semantics): a null/omitted side CLEARS that bracket."""

    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)


class TradeOut(BaseModel):
    id: int
    symbol: str
    strategy: str
    legs: list[TradeLeg]
    entry_date: datetime
    entry_underlying_price: float
    net_debit_credit: float
    status: TradeStatus
    exit_date: datetime | None = None
    exit_underlying_price: float | None = None
    realized_pnl: float | None = None
    is_paper: bool
    notes: str | None = None
    # Limit/stop orders + SL/TP brackets. order_type defaults to market so
    # legacy rows read as immediate fills. limit_price = option-premium entry
    # trigger; stop_loss/take_profit = underlying price levels (chart brackets).
    order_type: OrderType = "market"
    limit_price: float | None = None
    # stop_limit ENTRY: arms at stop_price, then rests as a limit at limit_price.
    stop_price: float | None = None
    # Trailing stop (EXIT): trails the favorable option mark by trail_amount
    # ($/share) or trail_pct; trail_hwm is the monitor-maintained high-water.
    trail_amount: float | None = None
    trail_pct: float | None = None
    trail_hwm: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    close_reason: CloseReason | None = None
    # Combine-tier introduction. Trades tagged with the tier they were
    # opened on; older rows (none exist post-wipe) default to "50K".
    tier: str = "50K"
    # Phase 2 enrichment.
    tags: list[str] = Field(default_factory=list)
    mistake_tags: list[str] = Field(default_factory=list)
    confidence: int | None = None
    thesis: str | None = None
    planned_exit: str | None = None
    risk_amount: float | None = None
    screenshot_url: str | None = None
    review_note: str | None = None
    r_multiple: float | None = None
    created_at: datetime
    updated_at: datetime


class TradesResponse(BaseModel):
    trades: list[TradeOut]


class AnalyticsGreeks(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float


class TradeAnalyticsOut(BaseModel):
    """Phase 2 analytics payload — drives the on-chart breakeven overlay
    and the payoff panel."""

    trade_id: int
    symbol: str
    spot: float
    rate: float
    current_dte_days: int
    scrubber_dte_days: int
    iv_used: float
    iv_source: Literal["implied_from_entry", "fallback", "default"]
    prices: list[float]
    payoff_expiration: list[float]
    payoff_today: list[float]
    breakevens_expiration: list[float]
    breakevens_today: list[float]
    entry_underlying_price: float
    entry_date: datetime
    cost_basis: float
    current_value: float
    unrealized_pnl: float
    # Simulated commission, $ per SIDE for this position (contracts × rate).
    # cost_basis includes the entry side; realized P&L on close subtracts
    # the exit side too. 0.0 default keeps older payloads valid.
    commission: float = 0.0
    max_profit: float | None = None
    max_loss: float | None = None
    unlimited_gain: bool
    unlimited_loss: bool
    greeks: AnalyticsGreeks


def compute_net_debit_credit(legs: list[TradeLeg]) -> float:
    """Net dollar cost of opening the position.

    Positive = debit (we paid); negative = credit (we received).
    Convention: each contract represents 100 shares (US equity options),
    so total $ = sum_over_legs((buy_price - sell_price) × contracts × 100).
    Sells reduce cost (subtract); buys add to cost.
    """
    total = 0.0
    for leg in legs:
        sign = 1.0 if leg.action == "buy" else -1.0
        total += sign * leg.entry_price * leg.contracts * 100
    return round(total, 2)


# Re-export for downstream router/seed code that wants the canonical list.
__all__ = [
    "AnalyticsGreeks",
    "EXPECTED_LEG_COUNT",
    "MISTAKE_TAG_VOCABULARY",
    "STRATEGY_TYPES",
    "TradeAnalyticsOut",
    "TradeIn",
    "TradeLeg",
    "TradeOut",
    "TradeStatus",
    "TradeUpdate",
    "TradesResponse",
    "compute_net_debit_credit",
]
