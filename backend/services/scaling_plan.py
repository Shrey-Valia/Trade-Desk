"""Scaling plan — maximum position size (contracts) per tier.

Flat per-tier cap, available from the start: 50K → 5, 100K → 10, 150K → 15.
(Per the account owner's preference — a higher, simpler cap than Topstep's
ramped build-equity table, which started 50K at 2 and unlocked 3/5 as profit
cleared $1.5K/$2K. We keep the (threshold, contracts) shape so a ramp can be
reintroduced later by adding steps; today each tier is a single step at $0.)

The cap is still aggregate-enforced on open (open + working ≤ max) and is
fixed intraday — `max_contracts` is keyed off settled profit but, with a
single step at $0, resolves to the tier max regardless.
"""

from __future__ import annotations

# Per tier: ascending steps of (min_profit_above_start, max_contracts).
SCALING_PLANS: dict[str, list[tuple[float, int]]] = {
    "50K": [(0.0, 5)],
    "100K": [(0.0, 10)],
    "150K": [(0.0, 15)],
}


def max_contracts(tier: str, settled_profit: float) -> int:
    """Allowed max contracts for `tier` given profit above the starting
    balance (settled-HWM basis). Returns the count for the highest step
    whose threshold is met; 1 for an unknown tier (fail safe)."""
    steps = SCALING_PLANS.get(tier)
    if not steps:
        return 1
    allowed = steps[0][1]
    for threshold, contracts in steps:
        if settled_profit >= threshold:
            allowed = contracts
    return allowed


def scaling_steps(tier: str) -> list[tuple[float, int]]:
    """The full (threshold, contracts) ladder for a tier — for display."""
    return list(SCALING_PLANS.get(tier, []))
