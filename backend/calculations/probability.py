"""Closed-form probability metrics — prob-ITM and probability of profit.

Risk-neutral lognormal probabilities under the same Black-Scholes model the
pricing engine uses:

    P(S_T > K) = N(d2),   d2 = [ln(S/K) + (r − σ²/2)·T] / (σ√T)

Prob-ITM for a call is N(d2) at the strike; a put is N(−d2). POP evaluates
the same integral at the BREAKEVEN(s) instead of the strike — the number
Tastytrade prints on every ticket. These are model probabilities (no vol
smile, risk-neutral drift): honest decision support, not a forecast.

Degenerate inputs (T or σ ≈ 0) collapse to the step function — the position
either is or isn't past the level.
"""

from __future__ import annotations

from math import log, sqrt

from scipy.stats import norm

_EPS = 1e-12


def prob_above(spot: float, level: float, t_years: float, rate: float, sigma: float) -> float:
    """Risk-neutral P(S_T > level) = N(d2 evaluated at K=level)."""
    if spot <= 0 or level <= 0:
        return 0.0 if spot <= level else 1.0
    if t_years <= _EPS or sigma <= _EPS:
        return 1.0 if spot > level else 0.0
    d2 = (log(spot / level) + (rate - 0.5 * sigma * sigma) * t_years) / (
        sigma * sqrt(t_years)
    )
    return float(norm.cdf(d2))


def prob_below(spot: float, level: float, t_years: float, rate: float, sigma: float) -> float:
    return 1.0 - prob_above(spot, level, t_years, rate, sigma)


def prob_itm(
    spot: float, strike: float, t_years: float, rate: float, sigma: float, side: str
) -> float:
    """Probability the option finishes in the money at expiry."""
    p_above = prob_above(spot, strike, t_years, rate, sigma)
    return p_above if side == "call" else 1.0 - p_above


def pop_from_curve(
    spot: float,
    breakevens: list[float],
    t_years: float,
    rate: float,
    sigma: float,
    payoff_at,
) -> float:
    """Generic POP for ANY expiry payoff: partition the price axis at the
    breakevens, test the payoff sign at a point inside each region, and sum
    the risk-neutral probability of the profitable regions. Exact for
    piecewise-linear option payoffs (the sign is constant between zero
    crossings). `payoff_at(price) -> $` evaluates the expiry P&L."""
    bes = sorted(b for b in breakevens if b > 0)
    if not bes:
        return 1.0 if payoff_at(spot) > 0 else 0.0
    total = 0.0
    for i in range(len(bes) + 1):
        lo = bes[i - 1] if i > 0 else None
        hi = bes[i] if i < len(bes) else None
        if lo is None:
            sample = (hi or spot) / 2.0
        elif hi is None:
            sample = lo * 1.5 + 1.0
        else:
            sample = (lo + hi) / 2.0
        if payoff_at(sample) <= 0:
            continue
        p_lo = 1.0 if lo is None else prob_above(spot, lo, t_years, rate, sigma)
        p_hi = 0.0 if hi is None else prob_above(spot, hi, t_years, rate, sigma)
        total += max(0.0, p_lo - p_hi)
    return max(0.0, min(1.0, total))


def pop_long(
    spot: float,
    breakevens: list[float],
    t_years: float,
    rate: float,
    sigma: float,
    side: str | None,
) -> float | None:
    """Probability of profit at expiry for the LONG side of the previewed
    structure. Single leg: past its one breakeven in the favorable direction.
    Long straddle (two breakevens): outside the band. None when the breakeven
    set doesn't match a shape we can price honestly."""
    bes = sorted(b for b in breakevens if b > 0)
    if len(bes) == 1 and side in ("call", "put"):
        if side == "call":
            return prob_above(spot, bes[0], t_years, rate, sigma)
        return prob_below(spot, bes[0], t_years, rate, sigma)
    if len(bes) == 2:  # long straddle: profit outside [lower, upper]
        return prob_below(spot, bes[0], t_years, rate, sigma) + prob_above(
            spot, bes[1], t_years, rate, sigma
        )
    return None
