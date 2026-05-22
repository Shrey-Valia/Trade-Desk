"""Black-Scholes-Merton pricing + greeks + strategy payoff math.

Per-share units throughout. Multiply by 100 only when displaying total
dollars (one contract = 100 shares).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.stats import norm

# Numerical guards — see Phase 5 plan, "Edge cases".
_MIN_T = 1.0 / 365.0  # one day in years
_MIN_SIGMA = 0.01     # 1% IV floor


@dataclass
class Leg:
    strike: float
    type: Literal["call", "put"]
    side: Literal["long", "short"]
    quantity: int
    iv: float        # leg-specific IV (fall back to ATM IV at construction time)
    T: float         # years to expiry for THIS leg
    premium: float   # cost basis per share (set at construction time via bs_price)


def bs_price(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> float:
    """Black-Scholes-Merton price per share. Handles T → 0 by returning intrinsic."""
    if T <= 0:
        return _intrinsic(S, K, option_type)
    T = max(T, _MIN_T)
    sigma = max(sigma, _MIN_SIGMA)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return float(S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
    return float(K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def _intrinsic(S: float, K: float, option_type: str) -> float:
    return max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)


def bs_greeks(
    S: float, K: float, T: float, r: float, sigma: float, option_type: str
) -> dict[str, float]:
    """Per-share greeks. Returns zero greeks for expired options (T ≤ 0)."""
    if T <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    T = max(T, _MIN_T)
    sigma = max(sigma, _MIN_SIGMA)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    pdf_d1 = float(norm.pdf(d1))
    gamma = pdf_d1 / (S * sigma * np.sqrt(T))
    vega = S * pdf_d1 * np.sqrt(T) * 0.01  # per 1% IV change
    if option_type == "call":
        delta = float(norm.cdf(d1))
        theta = (
            -S * pdf_d1 * sigma / (2 * np.sqrt(T))
            - r * K * np.exp(-r * T) * float(norm.cdf(d2))
        ) / 365
    else:
        delta = float(norm.cdf(d1)) - 1
        theta = (
            -S * pdf_d1 * sigma / (2 * np.sqrt(T))
            + r * K * np.exp(-r * T) * float(norm.cdf(-d2))
        ) / 365
    return {"delta": float(delta), "gamma": float(gamma), "theta": float(theta), "vega": float(vega)}


def _leg_sign(leg: Leg) -> int:
    return 1 if leg.side == "long" else -1


def cost_basis(legs: list[Leg]) -> float:
    """Net cost in per-share dollars. Positive = debit, negative = credit."""
    return sum(_leg_sign(leg) * leg.premium * leg.quantity for leg in legs)


def payoff_at_expiry(legs: list[Leg], prices: np.ndarray) -> np.ndarray:
    """Per-share P&L at expiry, vectorized over the price grid."""
    cb = cost_basis(legs)
    intrinsic = np.zeros_like(prices, dtype=float)
    for leg in legs:
        if leg.type == "call":
            leg_intrinsic = np.maximum(prices - leg.strike, 0)
        else:
            leg_intrinsic = np.maximum(leg.strike - prices, 0)
        intrinsic += _leg_sign(leg) * leg.quantity * leg_intrinsic
    return intrinsic - cb


def current_value(
    legs: list[Leg], prices: np.ndarray, r: float
) -> np.ndarray:
    """Mark-to-market P&L at each price, using BS at each leg's remaining T."""
    cb = cost_basis(legs)
    mtm = np.zeros_like(prices, dtype=float)
    for leg in legs:
        # Vectorize bs_price over prices (loop is fine; few hundred points × few legs).
        values = np.array(
            [bs_price(s, leg.strike, leg.T, r, leg.iv, leg.type) for s in prices]
        )
        mtm += _leg_sign(leg) * leg.quantity * values
    return mtm - cb


def breakevens(prices: np.ndarray, payoff: np.ndarray) -> list[float]:
    """Sign-change crossings of the payoff curve. Linear interpolation."""
    out: list[float] = []
    for i in range(len(payoff) - 1):
        a, b = payoff[i], payoff[i + 1]
        if a == 0:
            out.append(float(prices[i]))
        elif a * b < 0:
            # Linear interpolation between (prices[i], a) and (prices[i+1], b).
            t = a / (a - b)
            out.append(float(prices[i] + t * (prices[i + 1] - prices[i])))
    return out


def has_unlimited_loss(legs: list[Leg]) -> bool:
    """Net short call position (more shorts than longs, by quantity) → loss
    grows without bound as price rises. Puts are bounded because S ≥ 0."""
    return _net_call_position(legs) < 0


def has_unlimited_gain(legs: list[Leg]) -> bool:
    """Net long call position → gain grows without bound as price rises."""
    return _net_call_position(legs) > 0


def _net_call_position(legs: list[Leg]) -> int:
    return sum(_leg_sign(leg) * leg.quantity for leg in legs if leg.type == "call")


def sum_greeks(legs: list[Leg], spot: float, r: float) -> dict[str, float]:
    totals = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        g = bs_greeks(spot, leg.strike, leg.T, r, leg.iv, leg.type)
        sign = _leg_sign(leg) * leg.quantity
        for k in totals:
            totals[k] += sign * g[k]
    return totals
