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

from dataclasses import dataclass

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

    # Theta. A full 1-calendar-day step saturates at the expiry for a sub-day
    # (0DTE) option — T - one_day clamps to the 60s floor, so "per day" theta
    # becomes a meaningless function of the floor. When less than a day remains,
    # report the ACTUAL remaining time decay to expiry: value(now) → intrinsic
    # (T=0). For longer-dated options keep the standard 1-calendar-day step.
    if T <= one_day:
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        theta = intrinsic - base  # ≤ 0 for long premium; = −(remaining extrinsic)
    else:
        theta = bs_intraday(S, K, T - one_day, r, sigma, option_type) - base

    # Vega — per 1% IV bump (sigma is fractional, so +0.01 == +1%).
    up_iv = bs_intraday(S, K, T, r, sigma + 0.01, option_type)
    vega = up_iv - base

    return {
        "delta": float(delta),
        "gamma": float(gamma),
        "theta": float(theta),
        "vega": float(vega),
    }


CONTRACT_MULTIPLIER = 100
PREVIEW_GRID_POINTS = 81


def _zero_crossings(xs: np.ndarray, ys: np.ndarray) -> list[float]:
    """Linear-interpolated zero crossings of ys over xs — the breakevens."""
    out: list[float] = []
    for i in range(len(ys) - 1):
        a, b = float(ys[i]), float(ys[i + 1])
        if a == 0:
            out.append(float(xs[i]))
        elif a * b < 0:
            t = a / (a - b)
            out.append(float(xs[i] + t * (xs[i + 1] - xs[i])))
    return out


@dataclass(frozen=True)
class ContractPreview:
    prices: list[float]
    payoff_today: list[float]          # $ P&L at t_now across prices
    payoff_expiration: list[float]     # $ P&L at expiry across prices
    breakevens: list[float]            # expiration breakevens
    max_profit: float | None           # None = unbounded (net long call)
    max_loss: float                    # negative $ (the debit for long-only)
    greeks: dict[str, float]           # aggregated delta/gamma/theta/vega
    entry_price: float                 # per-share net premium (debit > 0)
    cost: float                        # entry_price × 100 × contracts


def compute_contract_preview(
    *,
    spot: float,
    rate: float,
    iv: float,
    t_now: float,
    legs: list[dict],
) -> ContractPreview:
    """Pre-trade payoff/greeks for a hypothetical position. `legs` are
    dicts: {side: 'call'|'put', action: 'buy'|'sell', strike, contracts,
    entry_price}. Mirrors the 0DTE math in routers/journal._intraday_analytics
    but for a contract that hasn't been opened — drives the contract-detail
    panel's payoff diagram. Per-share values × 100 = dollars."""
    def _sign(leg: dict) -> int:
        return 1 if str(leg.get("action", "buy")).lower() == "buy" else -1

    def _value(s: float, t: float) -> float:
        return sum(
            _sign(l) * int(l["contracts"])
            * bs_intraday(s, float(l["strike"]), t, rate, iv, str(l["side"]))
            for l in legs
        )

    def _intrinsic(s: float) -> float:
        total = 0.0
        for l in legs:
            k = float(l["strike"])
            it = max(s - k, 0.0) if l["side"] == "call" else max(k - s, 0.0)
            total += _sign(l) * int(l["contracts"]) * it
        return total

    prices = np.linspace(spot * 0.75, spot * 1.25, PREVIEW_GRID_POINTS)
    cb_ps = sum(_sign(l) * int(l["contracts"]) * float(l["entry_price"]) for l in legs)

    today_ps = np.array([_value(float(s), t_now) for s in prices]) - cb_ps
    exp_ps = np.array([_intrinsic(float(s)) for s in prices]) - cb_ps
    breakevens = _zero_crossings(prices, exp_ps)

    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for l in legs:
        g = greeks_intraday(spot, float(l["strike"]), t_now, rate, iv, str(l["side"]))
        sign_qty = _sign(l) * int(l["contracts"])
        for key in greeks:
            greeks[key] += sign_qty * g[key]

    # Long-only v1: max loss is the debit paid; gain is unbounded if any
    # net-long call, otherwise the long put's intrinsic at S→0 minus cost.
    cost = cb_ps * CONTRACT_MULTIPLIER
    net_long_call = sum(
        _sign(l) * int(l["contracts"]) for l in legs if l["side"] == "call"
    )
    if net_long_call > 0:
        max_profit: float | None = None
    else:
        floor_at_zero = _intrinsic(0.0) - cb_ps
        max_profit = float(floor_at_zero * CONTRACT_MULTIPLIER)
    max_loss = float(min(0.0, -cost))

    return ContractPreview(
        prices=[float(p) for p in prices],
        payoff_today=[float(v) for v in (today_ps * CONTRACT_MULTIPLIER)],
        payoff_expiration=[float(v) for v in (exp_ps * CONTRACT_MULTIPLIER)],
        breakevens=breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        greeks={k: float(v) for k, v in greeks.items()},
        entry_price=float(cb_ps),
        cost=float(cost),
    )
