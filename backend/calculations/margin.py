"""Margin / buying-power requirements for option structures.

Before this module the platform had NO capital constraint: order cost was
never checked against the balance and short options were free to write —
the only brakes were the contract cap and the drawdown floors. This module
prices what a position must set aside, per structure (no cross-margining —
conservative, and standard for a prop sim):

DEFINED-RISK (no naked side): requirement = the structure's max loss at
expiry — the debit for long premium, width − credit for credit spreads,
the worst wing for condors. Computed as the payoff minimum over the
critical points {S=0, every strike, past the top strike}; exact for
piecewise-linear option payoffs.

NAKED SIDES (net short calls and/or net short puts): a Reg-T-style
per-contract requirement on the net short quantity of that side:

    calls: max(naked_pct·S − OTM, naked_min_pct·S)·100 + short premium·100
    puts:  max(naked_pct·S − OTM, naked_min_pct·K)·100 + short premium·100

using the most-conservative short strike on the side (lowest short call /
highest short put). When BOTH sides are naked (short straddle/strangle)
the industry rule applies: the greater single side plus the other side's
short premium. A mixed structure (naked tail + defined-risk body, e.g. a
ratio spread) requires the naked requirement PLUS the bounded-region max
loss — the sum slightly overshoots a broker's paired-off decomposition
(it charges the whole bounded region, not just the spread's share), which
is the correct side to err on: the previous max() rule UNDERSTATED a 1×2
ratio spread by ~24% vs Reg-T sum-of-parts (review wave 8, finding 5).
Pure-naked and pure-defined shapes are unaffected (their other term is 0).

Rates default from config (margin_naked_pct / margin_naked_min_pct) at the
call site; this module stays pure and takes them as arguments.
"""

from __future__ import annotations

from typing import Any

CONTRACT_MULTIPLIER = 100.0


def _sign(leg: dict[str, Any]) -> float:
    return 1.0 if str(leg.get("action", "buy")).lower() == "buy" else -1.0


def _qty(leg: dict[str, Any]) -> int:
    return max(1, int(leg.get("contracts", 1) or 1))


def _payoff_at(legs: list[dict[str, Any]], s: float) -> float:
    """Expiry P&L per structure at underlying `s`, in dollars (premiums in)."""
    total = 0.0
    for leg in legs:
        k = float(leg.get("strike", 0.0) or 0.0)
        side = str(leg.get("side", "call")).lower()
        intrinsic = max(s - k, 0.0) if side == "call" else max(k - s, 0.0)
        total += _sign(leg) * _qty(leg) * (
            intrinsic - float(leg.get("entry_price", 0.0) or 0.0)
        )
    return total * CONTRACT_MULTIPLIER


def _net_side_qty(legs: list[dict[str, Any]], side: str) -> int:
    """Net signed contract count on one side; negative = net short."""
    return int(
        sum(_sign(leg) * _qty(leg) for leg in legs if leg.get("side") == side)
    )


def _naked_req_per_contract(
    side: str, strike: float, spot: float, premium: float,
    naked_pct: float, naked_min_pct: float,
) -> float:
    """Reg-T-style naked requirement for ONE contract, dollars."""
    if side == "call":
        otm = max(0.0, strike - spot)
        base = max(naked_pct * spot - otm, naked_min_pct * spot)
    else:
        otm = max(0.0, spot - strike)
        base = max(naked_pct * spot - otm, naked_min_pct * strike)
    return (base + max(0.0, premium)) * CONTRACT_MULTIPLIER


def _naked_side_req(
    legs: list[dict[str, Any]], side: str, net_short: int, spot: float,
    naked_pct: float, naked_min_pct: float,
) -> float:
    """Requirement for the net short exposure on one side, priced at the
    most-conservative short strike (lowest short call / highest short put)."""
    shorts = [
        leg for leg in legs
        if leg.get("side") == side and str(leg.get("action")).lower() == "sell"
    ]
    if not shorts or net_short <= 0:
        return 0.0
    pick = min if side == "call" else max
    worst = pick(shorts, key=lambda leg: float(leg.get("strike", 0.0) or 0.0))
    return net_short * _naked_req_per_contract(
        side,
        float(worst.get("strike", 0.0) or 0.0),
        spot,
        float(worst.get("entry_price", 0.0) or 0.0),
        naked_pct,
        naked_min_pct,
    )


def _short_premium(legs: list[dict[str, Any]], side: str) -> float:
    """Total short premium collected on one side, dollars."""
    return sum(
        _qty(leg) * float(leg.get("entry_price", 0.0) or 0.0) * CONTRACT_MULTIPLIER
        for leg in legs
        if leg.get("side") == side and str(leg.get("action")).lower() == "sell"
    )


def payoff_at_expiry(legs: list[dict[str, Any]], s: float) -> float:
    """Public expiry-payoff evaluator (dollars, premiums included) — the
    exact piecewise-linear function exact_breakevens() roots."""
    return _payoff_at(legs, s)


def exact_breakevens(legs: list[dict[str, Any]]) -> list[float]:
    """Exact zero-crossings of the piecewise-linear EXPIRY payoff, computed
    from the legs themselves — not from a display grid. The payoff's knots
    are S=0 and the strikes; between knots it's linear, and beyond the top
    strike it's linear with slope 100·(net call quantity)/$. A ±25% display
    grid misses crossings in the tails, which made POP print a hard 1.0/0.0
    for deep-ITM/OTM structures (review wave 9, finding 9)."""
    strikes = sorted(
        {float(leg.get("strike", 0.0) or 0.0) for leg in legs if leg.get("strike")}
    )
    if not strikes:
        return []
    knots = [0.0, *strikes]
    values = [_payoff_at(legs, s) for s in knots]
    crossings: list[float] = []
    for i in range(1, len(knots)):
        v0, v1 = values[i - 1], values[i]
        if v0 == 0.0:
            crossings.append(knots[i - 1])
        if (v0 < 0 < v1) or (v1 < 0 < v0):
            t = v0 / (v0 - v1)
            crossings.append(knots[i - 1] + t * (knots[i] - knots[i - 1]))
    if values[-1] == 0.0:
        crossings.append(knots[-1])
    # Tail beyond the top strike: slope = Σ sign·qty over CALL legs, ×100/$.
    tail_slope = 100.0 * sum(
        _sign(leg) * _qty(leg) for leg in legs if leg.get("side") == "call"
    )
    v_top = values[-1]
    if tail_slope != 0.0 and (v_top < 0) != (tail_slope < 0) and v_top != 0.0:
        crossings.append(knots[-1] + (-v_top) / tail_slope)
    # Dedup near-identical roots (a crossing exactly at a knot appears twice).
    out: list[float] = []
    for c in sorted(c for c in crossings if c > 0):
        if not out or abs(c - out[-1]) > 1e-9:
            out.append(round(c, 6))
    return out


def structure_requirement(
    legs: list[dict[str, Any]],
    spot: float,
    *,
    naked_pct: float = 0.20,
    naked_min_pct: float = 0.10,
) -> float:
    """$ margin requirement for one structure. See the module docstring."""
    if not legs:
        return 0.0
    strikes = sorted(
        {float(leg.get("strike", 0.0) or 0.0) for leg in legs if leg.get("strike")}
    )
    if not strikes:
        return 0.0

    net_calls = _net_side_qty(legs, "call")
    net_puts = _net_side_qty(legs, "put")
    naked_calls = max(0, -net_calls)
    naked_puts = max(0, -net_puts)

    # Critical points of the piecewise-linear expiry payoff. The point past
    # the top strike stands in for S→∞ ONLY when the tail is flat (no naked
    # calls); a naked-call tail is priced by the Reg-T branch instead.
    criticals = [0.0, *strikes, strikes[-1] * 1.5 + 1.0]
    if naked_calls > 0:
        criticals = criticals[:-1]  # tail belongs to the naked-call req
    if naked_puts > 0:
        criticals = criticals[1:]  # S=0 belongs to the naked-put req
    bounded_loss = max(
        (0.0, *(-_payoff_at(legs, s) for s in criticals))
    )

    if naked_calls == 0 and naked_puts == 0:
        return round(bounded_loss, 2)

    call_req = _naked_side_req(legs, "call", naked_calls, spot, naked_pct, naked_min_pct)
    put_req = _naked_side_req(legs, "put", naked_puts, spot, naked_pct, naked_min_pct)
    if naked_calls > 0 and naked_puts > 0:
        # Both sides naked (short straddle/strangle): the greater side plus
        # the other side's short premium — the standard combined-naked rule.
        if call_req >= put_req:
            naked_req = call_req + _short_premium(legs, "put")
        else:
            naked_req = put_req + _short_premium(legs, "call")
    else:
        naked_req = call_req + put_req
    # SUM, not max: a mixed structure's defined-risk body requires its own
    # collateral on top of the naked tail (max() understated ratio spreads —
    # see module docstring). Pure shapes are unchanged: a bare naked side has
    # bounded_loss 0 over its trimmed criticals, and a defined-risk structure
    # never reaches this branch.
    return round(naked_req + bounded_loss, 2)


def book_requirement(
    structures: list[tuple[list[dict[str, Any]], float]],
    *,
    naked_pct: float = 0.20,
    naked_min_pct: float = 0.10,
) -> float:
    """Aggregate requirement across a book: Σ per-structure requirements
    (no cross-margining). `structures` = [(legs, spot_for_its_symbol)]."""
    return round(
        sum(
            structure_requirement(
                legs, spot, naked_pct=naked_pct, naked_min_pct=naked_min_pct
            )
            for legs, spot in structures
        ),
        2,
    )
