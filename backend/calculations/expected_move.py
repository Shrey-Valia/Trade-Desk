"""±1σ expected move from the ATM straddle."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from calculations.types import ContractRow

# Heuristic adjustment for non-normality of returns. README §10.
STRADDLE_TO_SIGMA = 0.85


def expected_move(atm_call_price: float, atm_put_price: float) -> float:
    """1-sigma expected move ≈ straddle * 0.85."""
    return (atm_call_price + atm_put_price) * STRADDLE_TO_SIGMA


def expected_move_bands(spot: float, em: float) -> tuple[float, float]:
    """(upper, lower) absolute price levels."""
    return spot + em, spot - em


def atm_straddle_price(
    chain: Iterable[ContractRow], spot: float, expiry: date
) -> tuple[float, float] | None:
    """Locate ATM call+put for `expiry`, return (call_mid, put_mid).

    "Mid" prefers (bid+ask)/2, falls back to last, then to the larger of bid/ask.
    Returns None if no usable call+put pair exists at the ATM strike.
    """
    same_expiry = [c for c in chain if c.expiry == expiry]
    if not same_expiry:
        return None
    strikes = sorted({c.strike for c in same_expiry})
    if not strikes:
        return None
    atm_strike = min(strikes, key=lambda k: abs(k - spot))

    call = next(
        (c for c in same_expiry if c.type == "call" and c.strike == atm_strike), None
    )
    put = next(
        (c for c in same_expiry if c.type == "put" and c.strike == atm_strike), None
    )
    if call is None or put is None:
        return None

    cp = _mid(call)
    pp = _mid(put)
    if cp is None or pp is None:
        return None
    return cp, pp


def _mid(c: ContractRow) -> float | None:
    """Prefer a two-sided mid; fall back to a positive last. Returns None when
    only ONE side is quoted — a lone bid or ask is not a fair value for the
    contract, and using it skews the ±1σ expected-move band. (The old
    `c.bid or c.ask` fallback also mislabeled itself "larger of bid/ask" — it
    returned bid-if-truthy, not the larger.)"""
    if c.bid is not None and c.ask is not None and c.bid > 0 and c.ask > 0:
        return (c.bid + c.ask) / 2
    if c.last is not None and c.last > 0:
        return c.last
    return None
