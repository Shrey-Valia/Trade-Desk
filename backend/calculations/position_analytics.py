"""Trade Desk Phase 2 — position-level analytics with theta-decay scrubbing.

Builds the payload that drives both the on-chart breakeven overlay and
the payoff panel. Single source of math: reuses the BS engine in
black_scholes.py — we never re-implement option pricing here.

Two key ideas:
  1. The journal records an actual cost basis (`entry_price` per leg).
     We use that as the cost basis directly rather than re-pricing legs
     theoretically — the position's P&L is what the trader actually paid
     vs current value, not a model fitted from scratch.
  2. To preview theta decay, we clone legs with a shifted `T` (time-to-
     expiry) and re-run BS. `shift_legs_to_dte` advances all legs by the
     same elapsed window so calendar spreads still respect their offset.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import numpy as np
from scipy.optimize import brentq

from calculations.black_scholes import (
    Leg,
    bs_price,
    breakevens,
    cost_basis,
    current_value,
    has_unlimited_gain,
    has_unlimited_loss,
    payoff_at_expiry,
    sum_greeks,
)

# Price grid for payoff curves. ±25% around spot is enough to bracket
# the kink for any realistic single-month structure while keeping the
# response payload small.
GRID_HALFWIDTH = 0.25
GRID_POINTS = 81

# One option contract = 100 shares (US equity options). The BS module
# works in per-share dollars; we multiply at the boundary so the API
# returns total trade dollars throughout.
CONTRACT_MULTIPLIER = 100

# IV fallback when we can't back-solve from the entry premium and the
# live chain doesn't have a usable quote. 30% is a reasonable mid-vol
# default; flagged via `iv_source` in the payload so callers know.
DEFAULT_IV = 0.30


@dataclass
class AnalyticsResult:
    prices: list[float]
    payoff_expiration: list[float]
    payoff_today: list[float]
    breakevens_expiration: list[float]
    breakevens_today: list[float]
    current_value: float            # mark-to-market dollar value
    cost_basis: float               # what we paid / received, in dollars
    unrealized_pnl: float           # current_value - cost_basis
    max_profit: float | None
    max_loss: float | None
    unlimited_gain: bool
    unlimited_loss: bool
    greeks: dict[str, float]
    current_dte_days: int
    scrubber_dte_days: int
    iv_used: float
    iv_source: str


def implied_vol(
    market_price: float,
    spot: float,
    strike: float,
    T_years: float,
    rate: float,
    option_type: str,
) -> float | None:
    """Back-solve IV from an observed option price (Brent root-finder).

    Returns None when the price is below intrinsic + epsilon or above
    the upper-bound that brentq can bracket — those usually mean the
    entry_price was hand-entered as zero (untyped) and we shouldn't
    invent an IV. Caller falls back to live-chain or DEFAULT_IV.
    """
    if T_years <= 0 or market_price <= 0:
        return None

    def diff(sigma: float) -> float:
        return bs_price(spot, strike, T_years, rate, sigma, option_type) - market_price

    # Sanity-check brackets: at sigma=0.001 BS is essentially intrinsic;
    # at sigma=5 it covers >99% of any realistic IV range. If both
    # endpoints have the same sign brentq raises.
    try:
        lo, hi = diff(0.001), diff(5.0)
        if lo * hi > 0:
            return None
        return float(brentq(diff, 0.001, 5.0, xtol=1e-4, maxiter=64))
    except (ValueError, RuntimeError):
        return None


def build_legs_from_journal(
    journal_legs: list[dict[str, Any]],
    today: date,
    rate: float,
    spot_at_entry: float,
    entry_date: date,
    iv_fallback: float | None = None,
) -> tuple[list[Leg], float, str]:
    """Convert journal-style leg dicts to BS Leg objects.

    Cost basis comes from each leg's `entry_price` — we don't theoretical-
    price it from BS. We DO back-solve IV from the entry_price using the
    entry-time underlying + entry-time T, so the current-value math
    matches the trade's actual vol environment.

    Returns (legs, iv_used, iv_source) — `iv_source` is one of
    "implied_from_entry" | "fallback" | "default" so the API can
    surface how the analytics were anchored.
    """
    entry_T_per_leg: list[float] = []
    iv_candidates: list[float] = []

    for jl in journal_legs:
        expiry = _parse_date(jl["expiry"])
        # T at ENTRY time, used to back-solve IV.
        T_entry = max((expiry - entry_date).days / 365.0, 0.0)
        entry_T_per_leg.append(T_entry)

        opt_type = jl["side"]            # journal "side" is call/put
        iv = implied_vol(
            market_price=float(jl["entry_price"]),
            spot=spot_at_entry,
            strike=float(jl["strike"]),
            T_years=T_entry,
            rate=rate,
            option_type=opt_type,
        )
        if iv is not None:
            iv_candidates.append(iv)

    if iv_candidates:
        iv_used = float(np.median(iv_candidates))
        iv_source = "implied_from_entry"
    elif iv_fallback is not None and iv_fallback > 0:
        iv_used = iv_fallback
        iv_source = "fallback"
    else:
        iv_used = DEFAULT_IV
        iv_source = "default"

    legs: list[Leg] = []
    for jl in journal_legs:
        expiry = _parse_date(jl["expiry"])
        # T NOW — drives current_value math. Always recomputed from today.
        T_now = max((expiry - today).days / 365.0, 0.0)
        legs.append(
            Leg(
                strike=float(jl["strike"]),
                type=jl["side"],
                side=("long" if jl["action"] == "buy" else "short"),
                quantity=int(jl.get("contracts", 1)),
                iv=iv_used,
                T=T_now,
                premium=float(jl["entry_price"]),
            )
        )
    return legs, iv_used, iv_source


def shift_legs_to_dte(
    legs: list[Leg],
    current_dte_days: int,
    scrubber_dte_days: int,
) -> list[Leg]:
    """Clone legs with T shifted by (current - scrubber) calendar days.

    scrubber_dte_days == current_dte_days → unchanged (today).
    scrubber_dte_days == 0                 → advance to nearest expiry.
    Multi-expiry positions (calendar spreads) preserve their offset
    because we apply the same elapsed_years to every leg.
    """
    elapsed_years = max(0, current_dte_days - scrubber_dte_days) / 365.0
    return [replace(leg, T=max(0.0, leg.T - elapsed_years)) for leg in legs]


def nearest_dte_days(legs: list[Leg]) -> int:
    """Smallest T across legs, rounded to whole days. Drives the scrubber
    range — at scrubber=0 the nearest leg has expired."""
    if not legs:
        return 0
    return max(0, int(round(min(leg.T for leg in legs) * 365)))


def position_value_per_share(legs: list[Leg], spot: float, rate: float) -> float:
    """Theoretical per-share value at the legs' current T (and IV)."""
    total = 0.0
    for leg in legs:
        sign = 1 if leg.side == "long" else -1
        total += sign * leg.quantity * bs_price(
            spot, leg.strike, leg.T, rate, leg.iv, leg.type
        )
    return total


def compute_analytics(
    legs_now: list[Leg],
    spot: float,
    rate: float,
    *,
    scrubber_dte_days: int | None = None,
    iv_used: float,
    iv_source: str,
) -> AnalyticsResult:
    """Build the full analytics payload at a single (spot, DTE) snapshot.

    `legs_now` carries leg.T = (expiry - today). `scrubber_dte_days`
    advances time forward when set; if None we use the nearest-leg DTE
    (= today, the natural state).
    """
    current_dte = nearest_dte_days(legs_now)
    scrubber = scrubber_dte_days if scrubber_dte_days is not None else current_dte
    scrubber = max(0, min(current_dte, scrubber))

    legs_shifted = shift_legs_to_dte(legs_now, current_dte, scrubber)

    prices = np.linspace(
        spot * (1 - GRID_HALFWIDTH),
        spot * (1 + GRID_HALFWIDTH),
        GRID_POINTS,
    )

    # Per-share P&L vs cost basis.
    expiry_pnl_ps = payoff_at_expiry(legs_now, prices)
    today_pnl_ps = current_value(legs_shifted, prices, rate)

    # Cost basis from the JOURNAL entry prices (leg.premium) — not BS theory.
    cb_per_share = cost_basis(legs_now)
    cb_total = cb_per_share * CONTRACT_MULTIPLIER

    # Total-dollar payoffs.
    expiry_pnl = expiry_pnl_ps * CONTRACT_MULTIPLIER
    today_pnl = today_pnl_ps * CONTRACT_MULTIPLIER

    # Dedup defensively. The solver returns one crossing per sign change,
    # but a curve grazing zero across adjacent grid cells could emit
    # near-identical values; strip anything within $0.05 of a prior BE so
    # the chart doesn't render two overlapping magenta lines.
    be_expiry = _dedupe_sorted(sorted(breakevens(prices, expiry_pnl_ps)))
    be_today = _dedupe_sorted(sorted(breakevens(prices, today_pnl_ps)))

    cv_per_share = position_value_per_share(legs_shifted, spot, rate)
    cv_total = cv_per_share * CONTRACT_MULTIPLIER
    unrealized = cv_total - cb_total

    unlimited_gain = has_unlimited_gain(legs_now)
    unlimited_loss = has_unlimited_loss(legs_now)
    max_profit = None if unlimited_gain else float(np.max(expiry_pnl))
    max_loss = None if unlimited_loss else float(np.min(expiry_pnl))

    # Greeks at the scrubbed state — these are what the position LOOKS
    # like at the scrubber's point in time, not just today.
    greeks = sum_greeks(legs_shifted, spot, rate)
    # sum_greeks returns per-share; scale to position dollars.
    greeks_dollar = {k: v * CONTRACT_MULTIPLIER for k, v in greeks.items()}

    return AnalyticsResult(
        prices=[float(p) for p in prices],
        payoff_expiration=[float(v) for v in expiry_pnl],
        payoff_today=[float(v) for v in today_pnl],
        breakevens_expiration=be_expiry,
        breakevens_today=be_today,
        current_value=float(cv_total),
        cost_basis=float(cb_total),
        unrealized_pnl=float(unrealized),
        max_profit=max_profit,
        max_loss=max_loss,
        unlimited_gain=unlimited_gain,
        unlimited_loss=unlimited_loss,
        greeks=greeks_dollar,
        current_dte_days=current_dte,
        scrubber_dte_days=scrubber,
        iv_used=iv_used,
        iv_source=iv_source,
    )


def _parse_date(v: Any) -> date:
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def _dedupe_sorted(values: list[float], tol: float = 0.05) -> list[float]:
    """Drop entries within `tol` of the prior accepted value. Input
    expected to be sorted ascending. Used to scrub solver noise from
    the breakeven list so the chart doesn't draw two magenta lines on
    top of each other at the same price."""
    if not values:
        return []
    out = [float(values[0])]
    for v in values[1:]:
        if float(v) - out[-1] > tol:
            out.append(float(v))
    return out
