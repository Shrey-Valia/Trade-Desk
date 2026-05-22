"""GET /api/mc/{symbol} — GBM Monte Carlo + probability levels.

Cached 30s per (symbol, horizon, n_paths). The BS endpoint reuses the
same cache key, so /bs/payoff never re-runs MC for the same symbol —
satisfying the "don't see different sample paths every 5s" property.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, HTTPException

from calculations.expected_move import (
    atm_straddle_price,
    expected_move,
    expected_move_bands,
)
from calculations.gamma_exposure import gamma_flip, gex_by_strike, largest_oi_strike, max_pain
from calculations.monte_carlo import (
    monte_carlo_paths,
    percentile_bands,
    prob_close_above,
    prob_touch,
)
from schemas.mc import McProbabilityLevel, McResponse
from services.alpaca_client import get_quotes
from services.cache import cache
from services.finnhub_client import next_earnings_for

router = APIRouter(prefix="/api/mc", tags=["mc"])
log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_SAMPLE_PATHS_RETURNED = 25
_DEFAULT_PATHS = 10_000
_DEFAULT_HORIZON_FALLBACK = 7  # days when no near earnings


@router.get("/{symbol}", response_model=McResponse)
def get_mc(
    symbol: str,
    horizon_days: int | None = None,
    n_paths: int = _DEFAULT_PATHS,
) -> McResponse:
    symbol = symbol.upper()
    horizon = horizon_days or _resolve_default_horizon(symbol)
    return run_mc(symbol, horizon=horizon, n_paths=n_paths)


def run_mc(symbol: str, horizon: int, n_paths: int = _DEFAULT_PATHS) -> McResponse:
    """Cache-aware MC. Used by /api/mc and reused by /api/bs for prob_profit."""
    seed = _seed_for(symbol)
    cache_key = f"mc:{symbol}:{horizon}:{n_paths}:{seed}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Local import to avoid the chart router → mc router cycle.
    from routers.ticker import _chain_with_oi_proxy, _pick_near_term_expiry

    chain, _ = _chain_with_oi_proxy(symbol)
    quote = get_quotes([symbol]).get(symbol)
    if quote is None or not chain:
        raise HTTPException(503, f"Insufficient options data to model {symbol}")

    spot = quote.price
    expiry = _pick_near_term_expiry(chain)
    sigma = _atm_sigma(chain, spot, expiry) if expiry else None
    if sigma is None or sigma < 0.01:
        raise HTTPException(503, f"Insufficient options data to model {symbol} (no usable IV)")

    T = horizon / 252.0  # horizon expressed in trading-day years
    n_steps = max(horizon, 5)  # ensure ≥5 timesteps for a smooth fan

    paths = monte_carlo_paths(
        S0=spot, mu=0.0, sigma=sigma, T=T, n_steps=n_steps, n_paths=n_paths, seed=seed
    )
    bands = percentile_bands(paths)
    probabilities = _build_probabilities(chain, paths, spot, expiry)

    terminal = paths[:, -1]
    response = McResponse(
        symbol=symbol,
        horizon_days=horizon,
        n_paths=n_paths,
        sigma=sigma,
        spot=spot,
        mean_close=float(terminal.mean()),
        std_close=float(terminal.std()),
        ci_95=(float(np.percentile(terminal, 2.5)), float(np.percentile(terminal, 97.5))),
        sample_paths=paths[:_SAMPLE_PATHS_RETURNED].tolist(),
        bands={str(p): arr.tolist() for p, arr in bands.items()},
        probabilities=probabilities,
    )
    cache.set(cache_key, response, ttl_seconds=30)
    # Side-cache the full terminal-price distribution for BS's prob_profit —
    # the response only carries 25 sample paths, but BS needs the full 10K
    # to estimate prob_profit accurately. Same TTL.
    cache.set(_terminals_cache_key(symbol), terminal.copy(), ttl_seconds=30)
    return response


def _terminals_cache_key(symbol: str) -> str:
    return f"mc:terminals:{symbol}"


def get_cached_terminals(symbol: str) -> np.ndarray | None:
    """BS endpoint helper — read the full terminal distribution if MC ran recently."""
    return cache.get(_terminals_cache_key(symbol))


def _resolve_default_horizon(symbol: str) -> int:
    """Days until next earnings if ≤30, else 7."""
    next_er = next_earnings_for(symbol)
    if next_er:
        try:
            er_date = datetime.fromisoformat(next_er).date()
            days = (er_date - datetime.now(_ET).date()).days
            if 1 <= days <= 30:
                return days
        except ValueError:
            pass
    return _DEFAULT_HORIZON_FALLBACK


def _seed_for(symbol: str) -> int:
    """Deterministic per-symbol seed so paths don't reshuffle each cache miss."""
    return abs(hash(symbol)) % (2**32)


def _atm_sigma(chain, spot: float, expiry) -> float | None:
    """Mean of call+put IV at ATM strike for `expiry`. Falls back to whichever
    side has IV. Returns None when neither side has IV."""
    same = [c for c in chain if c.expiry == expiry]
    if not same:
        return None
    atm = min({c.strike for c in same}, key=lambda k: abs(k - spot))
    ivs = [c.iv for c in same if c.strike == atm and c.iv is not None]
    if not ivs:
        log.warning("ATM IV missing for expiry %s; MC cannot proceed", expiry)
        return None
    return sum(ivs) / len(ivs)


def _build_probabilities(chain, paths, spot, expiry) -> list[McProbabilityLevel]:
    levels: list[tuple[str, float]] = []

    # Expected move bands
    if expiry is not None:
        straddle = atm_straddle_price(chain, spot, expiry)
        if straddle is not None:
            em = expected_move(*straddle)
            upper, lower = expected_move_bands(spot, em)
            levels.append((f"+1σ {upper:.0f}", upper))
            levels.append((f"−1σ {lower:.0f}", lower))

    # OI walls
    cw = largest_oi_strike(chain, "call")
    if cw is not None:
        levels.append((f"call wall {cw[0]:.0f}", cw[0]))
    pw = largest_oi_strike(chain, "put")
    if pw is not None:
        levels.append((f"put wall {pw[0]:.0f}", pw[0]))

    # Max pain + gamma flip (gamma flip uses ±20% strike window per Phase 3)
    mp = max_pain(chain)
    if mp is not None:
        levels.append((f"max pain {mp:.0f}", mp))
    window = [c for c in chain if 0.8 * spot <= c.strike <= 1.2 * spot]
    gex = gex_by_strike(window, spot)
    gflip = gamma_flip(gex) if gex else None
    if gflip is not None:
        levels.append((f"γ flip {gflip:.0f}", gflip))

    return [
        McProbabilityLevel(
            label=label,
            level=level,
            prob_touch=prob_touch(paths, level, spot=spot),
            prob_close_above=prob_close_above(paths, level),
        )
        for label, level in levels
    ]
