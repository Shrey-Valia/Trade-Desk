"""Combine metadata: display-only objectives + account-code generation.

Deliberately OUTSIDE services/account_tiers.py — that module's
floor/settlement math is frozen. Profit targets here are presentation
("Path to Funding" progress on the dashboard), not enforcement: nothing
settles, passes, or fails a combine yet.

Targets mirror Topstep's ladder: 50K→$3K, 100K→$6K, 150K→$9K.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.pricing import DEFAULT_SPLIT

PROFIT_TARGETS: dict[str, float] = {
    "50K": 3_000.0,
    "100K": 6_000.0,
    "150K": 9_000.0,
}


def profit_target(tier: str) -> float:
    return PROFIT_TARGETS.get(tier, 0.0)


def payout_eligible(
    realized_pnl: float, funded: bool, split: float = DEFAULT_SPLIT
) -> float:
    """Dollars a FUNDED account can request as a payout: the trader's split
    of realized profit (the combine's chosen 80/20 or 50/50). Zero for
    accounts still in evaluation, not yet activated, or in the red."""
    if not funded:
        return 0.0
    return max(0.0, realized_pnl) * split


def objective_progress(tier: str, realized_pnl: float) -> float:
    """Fraction of the profit target reached, clamped to [0, 1]."""
    target = profit_target(tier)
    if target <= 0:
        return 0.0
    return max(0.0, min(1.0, realized_pnl / target))


def generate_account_code(db: Session, tier: str, user_id: int) -> str:
    """Topstep-style unique code: '{tier}TC-{user_id}-{8 digits}'.

    Uniqueness is enforced by the column constraint; this pre-checks to
    keep the common path clean and retries on the (astronomically rare)
    collision.
    """
    from models.combine import Combine

    for _ in range(10):
        code = f"{tier}TC-{user_id}-{secrets.randbelow(10**8):08d}"
        exists = db.execute(
            select(Combine.id).where(Combine.account_code == code)
        ).scalar_one_or_none()
        if exists is None:
            return code
    raise RuntimeError("could not generate a unique account code")
