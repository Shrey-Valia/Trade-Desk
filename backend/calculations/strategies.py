"""Map a strategy name + chain to a leg list. Pure, no I/O.

Used by the BS endpoint when the client asks for a built-in strategy
rather than a hand-specified leg list.
"""

from __future__ import annotations

from datetime import date
from typing import TypedDict

from calculations.types import ContractRow

STRATEGY_TYPES = (
    "long_straddle",
    "long_call",
    "long_put",
    "short_call",
    "short_put",
    "bull_call_spread",
    "bear_put_spread",
    "bull_put_spread",
    "bear_call_spread",
    "long_strangle",
    "iron_condor",
    "calendar_spread",
)


class LegSpec(TypedDict):
    strike: float
    type: str           # "call" / "put"
    side: str           # "long" / "short"
    quantity: int
    expiry: str         # ISO


def build_legs(
    strategy_type: str,
    chain: list[ContractRow],
    spot: float,
    expiry: date,
    far_expiry: date | None = None,
) -> list[LegSpec]:
    """Derive leg list from a strategy type using strikes available in the chain.

    Returns [] when the chain doesn't have the strikes needed (e.g. no
    expiry match). Caller should treat empty as "couldn't build".
    """
    same = [c for c in chain if c.expiry == expiry]
    strikes = sorted({c.strike for c in same})
    if not strikes:
        return []
    atm = min(strikes, key=lambda k: abs(k - spot))
    atm_idx = strikes.index(atm)
    iso = expiry.isoformat()

    def above(n: int = 1) -> float:
        return strikes[min(atm_idx + n, len(strikes) - 1)]

    def below(n: int = 1) -> float:
        return strikes[max(atm_idx - n, 0)]

    if strategy_type == "long_straddle":
        return [
            _leg(atm, "call", "long", iso),
            _leg(atm, "put", "long", iso),
        ]
    if strategy_type == "long_call":
        return [_leg(atm, "call", "long", iso)]
    if strategy_type == "long_put":
        return [_leg(atm, "put", "long", iso)]
    if strategy_type == "short_call":
        return [_leg(atm, "call", "short", iso)]
    if strategy_type == "short_put":
        return [_leg(atm, "put", "short", iso)]
    if strategy_type == "bull_call_spread":
        return [
            _leg(atm, "call", "long", iso),
            _leg(above(2), "call", "short", iso),
        ]
    if strategy_type == "bear_put_spread":
        return [
            _leg(atm, "put", "long", iso),
            _leg(below(2), "put", "short", iso),
        ]
    if strategy_type == "bull_put_spread":
        # Sell ATM put, buy lower-strike put for protection. Net credit.
        return [
            _leg(atm, "put", "short", iso),
            _leg(below(2), "put", "long", iso),
        ]
    if strategy_type == "bear_call_spread":
        # Sell ATM call, buy higher-strike call for protection. Net credit.
        return [
            _leg(atm, "call", "short", iso),
            _leg(above(2), "call", "long", iso),
        ]
    if strategy_type == "long_strangle":
        return [
            _leg(above(1), "call", "long", iso),
            _leg(below(1), "put", "long", iso),
        ]
    if strategy_type == "iron_condor":
        return [
            _leg(above(2), "call", "short", iso),
            _leg(above(4), "call", "long", iso),
            _leg(below(2), "put", "short", iso),
            _leg(below(4), "put", "long", iso),
        ]
    if strategy_type == "calendar_spread":
        if far_expiry is None or far_expiry == expiry:
            return []
        return [
            _leg(atm, "call", "short", iso),
            _leg(atm, "call", "long", far_expiry.isoformat()),
        ]
    return []


def _leg(strike: float, opt_type: str, side: str, expiry_iso: str) -> LegSpec:
    return LegSpec(strike=strike, type=opt_type, side=side, quantity=1, expiry=expiry_iso)
