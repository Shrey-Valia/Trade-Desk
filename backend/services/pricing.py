"""Combine pricing — the single source of truth for what a combine costs.

Trade Desk is a PAPER / simulated prop firm: no real money ever moves. But
the product presents real, honest pricing (no "$XX" placeholders), so this
is where the numbers live — one module the catalog cards, the order summary,
the purchase endpoint, and the payment ledger all read from. The frontend
mirrors these exact numbers in `frontend/src/lib/pricing.ts`; keep the two
in sync (test_pricing.py pins the matrix on this side).

Model (mirrors Topstep's dual structure, priced for options):

  * Two PATHS, chosen at purchase and fixed for the life of the combine:
      - "activation":    lower monthly + a one-time $149 activation fee,
                         charged when the eval passes and the account funds.
      - "no_activation": higher monthly (+$50/mo), $0 activation.
    Break-even is ~3 months ($149 / $50): pass fast → activation is cheaper,
    grind through resets → no-activation wins.

  * Two SPLITS, also chosen at purchase (options-market norm is 80/20):
      - "80_20" (0.80): the standard split, normal price.
      - "50_50" (0.50): a budget split that knocks $10/mo off the monthly.

Monthly prices (with-activation, 80/20 = the base, options premium over
Topstep's futures pricing):

      50K → $69      100K → $119      150K → $169

No-activation adds a flat +$50/mo; the 50/50 split subtracts $10/mo. Every
dollar here is simulated — it is recorded in the payments ledger so each
combine traces to a purchase, but nothing is actually charged.
"""

from __future__ import annotations

from typing import Literal

PricingPath = Literal["activation", "no_activation"]
SplitToken = Literal["80_20", "50_50"]

# Base monthly subscription: the WITH-ACTIVATION, 80/20 price per tier.
BASE_MONTHLY: dict[str, float] = {
    "50K": 69.0,
    "100K": 119.0,
    "150K": 169.0,
}

# One-time fee to activate a funded account on the "activation" path. Flat
# across all sizes (Topstep-style). $0 on the "no_activation" path.
ACTIVATION_FEE: float = 149.0

# The "no_activation" path trades a higher monthly for a $0 activation fee.
NO_ACTIVATION_PREMIUM: float = 50.0

# The 50/50 budget split knocks this off the monthly vs the 80/20 default.
SPLIT_DISCOUNT: float = 10.0

# Split token → trader's share of funded profit.
SPLIT_VALUES: dict[str, float] = {
    "80_20": 0.80,
    "50_50": 0.50,
}

DEFAULT_PATH: PricingPath = "activation"
DEFAULT_SPLIT_TOKEN: SplitToken = "80_20"
DEFAULT_SPLIT: float = SPLIT_VALUES[DEFAULT_SPLIT_TOKEN]


def split_value(token: str) -> float:
    """Trader's profit share for a split token (defaults to 80/20)."""
    return SPLIT_VALUES.get(token, DEFAULT_SPLIT)


def split_token(value: float) -> SplitToken:
    """Reverse of split_value: snap a stored split float to its token."""
    return "50_50" if round(value, 2) == 0.50 else "80_20"


def monthly_price(tier: str, path: str = DEFAULT_PATH, split: float = DEFAULT_SPLIT) -> float:
    """Monthly subscription for a combine: base + no-activation premium −
    split discount. Raises KeyError on an unknown tier (callers validate
    the tier at the API boundary first)."""
    price = BASE_MONTHLY[tier]
    if path == "no_activation":
        price += NO_ACTIVATION_PREMIUM
    if round(split, 2) == 0.50:
        price -= SPLIT_DISCOUNT
    return round(price, 2)


def activation_fee(path: str) -> float:
    """One-time activation fee for the path: $149 on the activation path,
    $0 on the no-activation path (the account funds for free)."""
    return ACTIVATION_FEE if path == "activation" else 0.0


def quote(tier: str, path: str = DEFAULT_PATH, split: float = DEFAULT_SPLIT) -> dict:
    """A full price quote for one (tier, path, split) — what the order
    summary and the payment ledger read."""
    return {
        "tier": tier,
        "pricing_path": path,
        "profit_split": round(split, 2),
        "monthly_price": monthly_price(tier, path, split),
        "activation_fee": activation_fee(path),
    }
