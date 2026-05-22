"""Max pain, GEX by strike, gamma flip, OI walls."""

from __future__ import annotations

from collections.abc import Iterable

from calculations.types import ContractRow


def max_pain(chain: Iterable[ContractRow]) -> float | None:
    """Strike where total option-holder intrinsic value is minimized.

    For each candidate strike K:
      pain(K) = Σ over calls (oi * max(K - strike_call, 0))
              + Σ over puts  (oi * max(strike_put - K, 0))
    Return argmin.
    """
    rows = [c for c in chain if c.open_interest is not None and c.open_interest > 0]
    if not rows:
        return None
    strikes = sorted({c.strike for c in rows})
    if not strikes:
        return None

    best_k = None
    best_pain = float("inf")
    for k in strikes:
        pain = 0.0
        for r in rows:
            if r.type == "call":
                pain += r.open_interest * max(k - r.strike, 0)
            elif r.type == "put":
                pain += r.open_interest * max(r.strike - k, 0)
        if pain < best_pain:
            best_pain = pain
            best_k = k
    return best_k


def gex_by_strike(chain: Iterable[ContractRow], spot: float) -> dict[float, float]:
    """Dealer net gamma exposure per strike, $/1% move.

    Sign convention: dealers assumed short calls (-1), long puts (+1) — the
    standard simplification used by SpotGamma-style estimates. Returns {} when
    no contract has both OI and gamma populated.
    """
    out: dict[float, float] = {}
    for c in chain:
        if c.open_interest is None or c.gamma is None:
            continue
        sign = -1 if c.type == "call" else +1
        contribution = sign * c.open_interest * 100 * c.gamma * (spot ** 2) * 0.01
        out[c.strike] = out.get(c.strike, 0.0) + contribution
    return out


def gamma_flip(gex: dict[float, float]) -> float | None:
    """Lowest strike at which cumulative GEX (ascending) crosses ≥ 0.

    Above this level dealers stabilize price; below, they amplify moves.
    Returns None when GEX dict is empty or never crosses zero.
    """
    if not gex:
        return None
    cumulative = 0.0
    for k in sorted(gex.keys()):
        cumulative += gex[k]
        if cumulative >= 0:
            return k
    return None


def largest_oi_strike(chain: Iterable[ContractRow], side: str) -> tuple[float, int] | None:
    """Strike with the largest open interest on the requested side.

    Returns (strike, oi) or None if no `side` contracts have OI.
    """
    by_strike: dict[float, int] = {}
    for c in chain:
        if c.type != side:
            continue
        if c.open_interest is None or c.open_interest <= 0:
            continue
        by_strike[c.strike] = by_strike.get(c.strike, 0) + c.open_interest
    if not by_strike:
        return None
    strike = max(by_strike, key=by_strike.get)
    return strike, by_strike[strike]
