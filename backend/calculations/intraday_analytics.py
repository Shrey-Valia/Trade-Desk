"""Intraday (sub-day) Black-Scholes helpers — used by 0DTE flows.

The shared engine in `black_scholes.py` floors T at one day (`_MIN_T =
1/365`) because the integer-day position-analytics path can't represent
sub-day expirations. That floor is correct for multi-day positions but
makes intraday decay invisible — the same call returns the same price
at 6h-to-expiry as at 6min-to-expiry.

These helpers are byte-identical formulas (Black-Scholes-Merton on
European options, scipy.stats.norm CDF), differing only in the floor:
one minute (1/525_600 yr) instead of one day. They are NOT a fork of
the engine — they are an additional code path. The engine file stays
frozen.

Used by:
  - routers/zerodte.py     (the chain/open endpoints + the /mark legacy)
  - routers/journal.py     (intraday branch of /trades/{id}/analytics)
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

SECONDS_PER_YEAR = 365 * 24 * 3600
# One minute in years — the intraday T floor. Same role as
# black_scholes._MIN_T but four orders of magnitude tighter.
MIN_T_INTRADAY = 60.0 / SECONDS_PER_YEAR
MIN_SIGMA = 0.01


def bs_intraday(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> float:
    """Per-share Black-Scholes price with a 1-minute T-floor."""
    if T <= 0:
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        return intrinsic
    T = max(T, MIN_T_INTRADAY)
    sigma = max(sigma, MIN_SIGMA)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return float(S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
    return float(K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def iv_intraday(
    price: float, S: float, K: float, T: float, r: float, option_type: str
) -> float | None:
    """Back-solve IV for an intraday leg via Brent's method."""
    if price <= 0 or S <= 0 or K <= 0 or T <= 0:
        return None
    try:
        return float(
            brentq(
                lambda sigma: bs_intraday(S, K, T, r, sigma, option_type) - price,
                0.005,
                5.0,
                maxiter=128,
                xtol=1e-6,
            )
        )
    except (ValueError, RuntimeError):
        return None


def greeks_intraday(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> dict[str, float]:
    """Per-share greeks via central finite differences against bs_intraday.

    Same conventions as calculations.black_scholes.bs_greeks:
      * delta — ∂Value/∂S      per $1 of underlying
      * gamma — ∂²Value/∂S²
      * theta — ∂Value/∂t       per CALENDAR DAY (negative for long premium)
      * vega  — ∂Value/∂σ       per 1% IV change

    Used by the 0DTE branch only; multi-day positions go through the
    engine's bs_greeks (with the 1-day T floor — appropriate there).
    Returns zeros if T<=0, mirroring the engine's "expired" guard."""
    if T <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

    # Step sizes: small relative to typical scales but large enough to
    # avoid floating-point cancellation at the 1-minute T floor.
    h_s = max(0.05, S * 0.001)
    one_day = 1.0 / 365.0

    base = bs_intraday(S, K, T, r, sigma, option_type)
    up_s = bs_intraday(S + h_s, K, T, r, sigma, option_type)
    dn_s = bs_intraday(S - h_s, K, T, r, sigma, option_type)
    delta = (up_s - dn_s) / (2 * h_s)
    gamma = (up_s - 2 * base + dn_s) / (h_s ** 2)

    # Theta — 1-calendar-day forward step, floored so a near-expiry
    # position doesn't push T through zero.
    T_minus = max(MIN_T_INTRADAY, T - one_day)
    theta = bs_intraday(S, K, T_minus, r, sigma, option_type) - base

    # Vega — per 1% IV bump (sigma is fractional, so +0.01 == +1%).
    up_iv = bs_intraday(S, K, T, r, sigma + 0.01, option_type)
    vega = up_iv - base

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta),
        "vega": float(vega),
    }
