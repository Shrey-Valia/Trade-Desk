"""Scaling plan — maximum position size (contracts) by built equity.

Topstep model: the max contracts you may hold scales with your settled
(end-of-day) balance and only changes at the session boundary, never
intraday. We anchor it on the SETTLED HWM above the starting balance — the
same fixed-intraday anchor as the MLL floor — so a trader's allowed size
can't jump mid-session and re-evaluates at the 5pm-PT settlement.

The 50K plan is Topstep's published table (2 contracts to start, 3 once
profit clears $1,500, 5 once it clears $2,000; max 5). The 100K/150K plans
are derived proportionally by account size (2× / 3× on both the contract
counts and the profit thresholds), which lands on Topstep's documented
maxes of 10 and 15 — a principled extrapolation from the one verbatim
table, not invented figures.

Simplification vs. Topstep: we key off the settled HWM (built equity high),
so allowed size only ratchets UP. Topstep keys off the EOD balance, which
can fall and reduce size. Keying off the HWM keeps us consistent with the
MLL basis and avoids persisting a separate settled-balance column.
"""

from __future__ import annotations

# Per tier: ascending steps of (min_profit_above_start, max_contracts).
SCALING_PLANS: dict[str, list[tuple[float, int]]] = {
    "50K": [(0.0, 2), (1_500.0, 3), (2_000.0, 5)],
    "100K": [(0.0, 4), (3_000.0, 6), (4_000.0, 10)],
    "150K": [(0.0, 6), (4_500.0, 9), (6_000.0, 15)],
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
