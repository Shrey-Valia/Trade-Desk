"""Combine-tier definitions and MLL math.

Topstep / Apex / Tradeify industry-standard prop-firm combine sizes
and trailing drawdown distances. Three tiers, fixed parameters. No
custom tiers, no user-configurable starting balances — that's a
deliberate choice that mirrors the real prop-firm products and keeps
the model honest.

MLL ("Maximum Loss Limit") trails the account's high-water mark up by
the tier's trailing distance and is CAPPED at the starting balance
(Topstep / Tradeify behavior). The math lives here so the router, the
schemas, and any future enforcement code share one implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TierKey = Literal["50K", "100K", "150K"]
ALL_TIERS: tuple[TierKey, ...] = ("50K", "100K", "150K")
DEFAULT_TIER: TierKey = "50K"


@dataclass(frozen=True)
class Tier:
    key: TierKey
    label: str
    starting_balance: float
    trailing_distance: float
    # DLL ("Daily Loss Limit") — resets at the start of each ET trading
    # day. Separate from MLL (which is a permanent trailing floor that
    # never resets daily). Topstep-aligned 3% of starting balance.
    dll_amount: float

    @property
    def initial_mll(self) -> float:
        return self.starting_balance - self.trailing_distance


TIERS: dict[TierKey, Tier] = {
    "50K": Tier(
        key="50K",
        label="50K Combine",
        starting_balance=50_000.0,
        trailing_distance=2_000.0,
        dll_amount=1_500.0,
    ),
    "100K": Tier(
        key="100K",
        label="100K Combine",
        starting_balance=100_000.0,
        # Topstep convention: 50K→$2k, 100K→$3k, 150K→$4.5k trailing drawdown.
        trailing_distance=3_000.0,
        dll_amount=3_000.0,
    ),
    "150K": Tier(
        key="150K",
        label="150K Combine",
        starting_balance=150_000.0,
        trailing_distance=4_500.0,
        dll_amount=4_500.0,
    ),
}


def is_valid_tier(s: str) -> bool:
    return s in TIERS


# A user's custom DLL may sit anywhere in this band of the tier's starting
# balance (mirrors the frontend's 1-10% slider). Values outside are clamped.
DLL_OVERRIDE_MIN_FRAC = 0.01
DLL_OVERRIDE_MAX_FRAC = 0.10


def resolve_dll_budget(tier_key: TierKey, override: float | None) -> float:
    """The effective Daily Loss Limit for a tier: the user's override clamped
    to the 1-10%-of-starting-balance band, or the tier default when unset."""
    tier = TIERS[tier_key]
    if override is None:
        return tier.dll_amount
    lo = DLL_OVERRIDE_MIN_FRAC * tier.starting_balance
    hi = DLL_OVERRIDE_MAX_FRAC * tier.starting_balance
    return min(max(float(override), lo), hi)


def compute_mll(
    tier_key: TierKey,
    high_water_mark: float,
) -> float:
    """Trailing MLL given the tier and the running HWM.

    raw   = hwm - trailing_distance
    final = min(raw, starting_balance)   # capped at starting balance

    The cap is the Topstep / Tradeify rule: once the trail reaches the
    starting balance, it stops climbing — your MLL plateau is your
    starting capital, not above it.
    """
    tier = TIERS[tier_key]
    raw = high_water_mark - tier.trailing_distance
    return min(raw, tier.starting_balance)


def compute_balance(
    starting_balance: float,
    realized_pnl_sum: float,
    unrealized_pnl: float,
) -> float:
    """Live balance — starting capital plus realized P&L on closed
    trades plus any currently-open position's unrealized P&L."""
    return starting_balance + realized_pnl_sum + unrealized_pnl


def update_hwm(prior_hwm: float, current_balance: float) -> float:
    """High-water mark is monotonic — never decreases."""
    return max(prior_hwm, current_balance)
