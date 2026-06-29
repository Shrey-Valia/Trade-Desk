"""Monte-Carlo terminal-value simulation for an option position (WS5).

A self-contained scenario engine: given a position's legs, the current
spot, and a vol/rate environment, simulate the underlying's terminal
price under geometric Brownian motion and evaluate each path's P&L at
EXPIRY (intrinsic) so we can report a terminal-value distribution and
P(profit).

Design choices
--------------
  * Per-share dollars internally; ×100 at the boundary (one contract =
    100 shares), matching position_analytics.CONTRACT_MULTIPLIER.
  * Cost basis comes from each leg's `entry_price` (what the trader paid
    / received) — we never re-price the legs from a model. This keeps the
    P&L consistent with the journal and the payoff panel.
  * GBM with drift = risk-free rate (risk-neutral) by default; the caller
    may pass an explicit annualized drift to explore a directional view.
  * Deterministic when a `seed` is supplied so tests + replays are stable.
  * Pure-numpy, no DB / network — trivially unit-testable and reusable by
    the /api/analytics/montecarlo endpoint.

The legs are journal-style dicts:
    {side: 'call'|'put', action: 'buy'|'sell', strike, contracts, entry_price}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

CONTRACT_MULTIPLIER = 100

# Guard rails so a degenerate request can't blow up or hang.
MAX_PATHS = 200_000
MIN_PATHS = 100
_TRADING_DAYS_PER_YEAR = 252.0


@dataclass(frozen=True)
class MonteCarloResult:
    """Terminal-value distribution + summary stats for a position.

    All P&L figures are TOTAL dollars (per-share × 100 × contracts).
    `pnl_histogram` buckets the simulated terminal P&L; `terminal_prices_*`
    summarise the simulated underlying at expiry.
    """

    paths: int
    horizon_days: float
    spot: float
    sigma: float
    drift: float
    cost_basis: float            # net debit (>0) / credit (<0), total $
    prob_profit: float           # fraction of paths with P&L > 0
    expected_pnl: float          # mean terminal P&L, total $
    median_pnl: float
    pnl_p05: float               # 5th percentile (downside)
    pnl_p95: float               # 95th percentile (upside)
    max_simulated_loss: float
    max_simulated_profit: float
    var_95: float                # 95% Value-at-Risk (a positive loss magnitude)
    expected_terminal_price: float
    # Distribution for the UI histogram.
    hist_bin_edges: list[float]  # len = bins + 1, in P&L dollars
    hist_counts: list[int]       # len = bins
    # A small sample of terminal prices for a scatter/strip, capped.
    sample_terminal_prices: list[float]


def _leg_sign(action: str) -> int:
    return 1 if str(action).lower() == "buy" else -1


def position_cost_basis(legs: list[dict[str, Any]]) -> float:
    """Net cost basis in TOTAL dollars. Positive = debit paid, negative =
    credit received. Uses the legs' actual entry_price, not a model."""
    cb_ps = sum(
        _leg_sign(leg.get("action", "buy"))
        * int(leg.get("contracts", 1))
        * float(leg["entry_price"])
        for leg in legs
    )
    return cb_ps * CONTRACT_MULTIPLIER


def _intrinsic_value_ps(legs: list[dict[str, Any]], terminal: np.ndarray) -> np.ndarray:
    """Per-share intrinsic value of the whole position at each terminal
    price (vectorised). Longs add, shorts subtract."""
    total = np.zeros_like(terminal, dtype=float)
    for leg in legs:
        k = float(leg["strike"])
        qty = int(leg.get("contracts", 1))
        sign = _leg_sign(leg.get("action", "buy"))
        if str(leg["side"]).lower() == "call":
            leg_intrinsic = np.maximum(terminal - k, 0.0)
        else:
            leg_intrinsic = np.maximum(k - terminal, 0.0)
        total += sign * qty * leg_intrinsic
    return total


def simulate_terminal_pnl(
    *,
    legs: list[dict[str, Any]],
    spot: float,
    sigma: float,
    horizon_days: float,
    rate: float = 0.0,
    drift: float | None = None,
    paths: int = 10_000,
    seed: int | None = None,
) -> MonteCarloResult:
    """Simulate the position's P&L at EXPIRY under GBM.

    Parameters
    ----------
    legs      : journal-style leg dicts (see module docstring).
    spot      : current underlying price (>0).
    sigma     : annualized volatility (e.g. 0.30). Floored at 1e-4.
    horizon_days : calendar/trading days to the position's expiry. A 0DTE
                   position uses the fractional remaining session; clamped
                   to a tiny positive floor so terminal != spot exactly.
    rate      : annualized risk-free rate (drift default when `drift` None).
    drift     : optional explicit annualized drift to model a directional
                view; defaults to the risk-neutral `rate`.
    paths     : number of simulated paths (clamped to [MIN, MAX]_PATHS).
    seed      : RNG seed for deterministic output.

    Terminal price under GBM:
        S_T = S * exp((mu - 0.5 sigma^2) T + sigma sqrt(T) Z),  Z ~ N(0,1)
    """
    if spot <= 0:
        raise ValueError("spot must be > 0")
    if not legs:
        raise ValueError("legs must be non-empty")

    n = int(max(MIN_PATHS, min(MAX_PATHS, paths)))
    sigma = max(float(sigma), 1e-4)
    # Years to expiry; floor at ~1 minute so a 0DTE horizon still has spread.
    t_years = max(float(horizon_days), 1.0 / _TRADING_DAYS_PER_YEAR / 390.0) / _TRADING_DAYS_PER_YEAR
    mu = float(rate) if drift is None else float(drift)

    rng = np.random.default_rng(seed)
    z = rng.standard_normal(n)
    terminal = spot * np.exp(
        (mu - 0.5 * sigma**2) * t_years + sigma * np.sqrt(t_years) * z
    )

    intrinsic_ps = _intrinsic_value_ps(legs, terminal)
    cb_total = position_cost_basis(legs)
    # P&L = (terminal intrinsic value) − cost basis, all in total dollars.
    pnl = intrinsic_ps * CONTRACT_MULTIPLIER - cb_total

    prob_profit = float(np.mean(pnl > 0.0))
    expected_pnl = float(np.mean(pnl))
    median_pnl = float(np.median(pnl))
    p05 = float(np.percentile(pnl, 5))
    p95 = float(np.percentile(pnl, 95))
    # 95% VaR: the loss magnitude not exceeded 95% of the time. Reported as a
    # positive number (0 if the 5th-percentile outcome is still a profit).
    var_95 = float(max(0.0, -p05))

    bins = 40
    counts, edges = np.histogram(pnl, bins=bins)

    # Cap the scatter sample so the payload stays small.
    sample_cap = 500
    if n > sample_cap:
        idx = rng.choice(n, size=sample_cap, replace=False)
        sample = terminal[idx]
    else:
        sample = terminal

    return MonteCarloResult(
        paths=n,
        horizon_days=float(horizon_days),
        spot=float(spot),
        sigma=float(sigma),
        drift=float(mu),
        cost_basis=float(cb_total),
        prob_profit=prob_profit,
        expected_pnl=expected_pnl,
        median_pnl=median_pnl,
        pnl_p05=p05,
        pnl_p95=p95,
        max_simulated_loss=float(np.min(pnl)),
        max_simulated_profit=float(np.max(pnl)),
        var_95=var_95,
        expected_terminal_price=float(np.mean(terminal)),
        hist_bin_edges=[float(e) for e in edges],
        hist_counts=[int(c) for c in counts],
        sample_terminal_prices=[float(s) for s in sample],
    )
