"""POST /api/bs/payoff and GET /api/bs/strategy/{symbol}/{type}.

Strategy-builder convenience GET derives default legs from the chain so
the frontend can render a default panel without having to know strikes.
The POST endpoint is the workhorse — accepts an explicit leg list and
returns payoff curves + greeks + prob_profit.

prob_profit is sourced from the cached MC distribution for the same
symbol — no re-run per strategy.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, HTTPException

from calculations.black_scholes import (
    Leg,
    breakevens,
    bs_price,
    cost_basis,
    current_value,
    has_unlimited_gain,
    has_unlimited_loss,
    payoff_at_expiry,
    sum_greeks,
)
from calculations.strategies import STRATEGY_TYPES, build_legs
from routers.mc import _resolve_default_horizon, get_cached_terminals, run_mc
from schemas.bs import BsGreeks, BsPoint, BsRequest, BsResponse
from services.alpaca_client import get_quotes
from services.cache import cache
from services.fred_client import latest_dgs3mo_rate

router = APIRouter(prefix="/api/bs", tags=["bs"])
log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_PRICE_GRID_POINTS = 100
_PRICE_GRID_HALFWIDTH = 0.20  # ±20% of spot


@router.get("/strategy/{symbol}/{strategy_type}", response_model=BsResponse)
def get_strategy(symbol: str, strategy_type: str) -> BsResponse:
    """Build the default leg list for `strategy_type` and price it.

    Convenience endpoint so the frontend can render a default strategy
    on ticker click without having to enumerate strikes itself.
    """
    symbol = symbol.upper()
    if strategy_type not in STRATEGY_TYPES:
        raise HTTPException(400, f"unknown strategy type {strategy_type!r}")

    from routers.ticker import _chain_with_oi_proxy, _pick_near_term_expiry

    chain, _ = _chain_with_oi_proxy(symbol)
    quote = get_quotes([symbol]).get(symbol)
    if not chain or quote is None:
        raise HTTPException(503, f"Insufficient options data to model {symbol}")

    near = _pick_near_term_expiry(chain)
    if near is None:
        raise HTTPException(503, f"No usable expiry for {symbol}")

    far = _pick_far_expiry(chain, after=near)
    legs_in = build_legs(strategy_type, chain, quote.price, near, far)
    if not legs_in:
        raise HTTPException(503, f"Could not build {strategy_type} from chain")

    return _price_legs(symbol, legs_in)


@router.post("/payoff", response_model=BsResponse)
def post_payoff(req: BsRequest) -> BsResponse:
    legs_in = [leg.model_dump() for leg in req.legs]
    return _price_legs(
        req.symbol.upper(),
        legs_in,
        iv_override=req.iv_override,
        rate_override=req.rate,
    )


def _price_legs(
    symbol: str,
    legs_in: list[dict],
    iv_override: float | None = None,
    rate_override: float | None = None,
) -> BsResponse:
    cache_key = f"bs:{symbol}:{_legs_cache_key(legs_in, iv_override, rate_override)}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    from routers.ticker import _chain_with_oi_proxy

    chain, _ = _chain_with_oi_proxy(symbol)
    quote = get_quotes([symbol]).get(symbol)
    if not chain or quote is None:
        raise HTTPException(503, f"Insufficient options data to model {symbol}")
    spot = quote.price
    today = datetime.now(_ET).date()
    rate = rate_override if rate_override is not None else latest_dgs3mo_rate()

    legs = _hydrate_legs(legs_in, chain, spot, today, rate, iv_override)
    if not legs:
        raise HTTPException(503, f"Could not price legs for {symbol}")

    prices = np.linspace(spot * (1 - _PRICE_GRID_HALFWIDTH), spot * (1 + _PRICE_GRID_HALFWIDTH), _PRICE_GRID_POINTS)
    expiry_pnl = payoff_at_expiry(legs, prices)
    cur_val = current_value(legs, prices, r=rate)
    greeks = sum_greeks(legs, spot=spot, r=rate)

    unlimited_loss = has_unlimited_loss(legs)
    unlimited_gain = has_unlimited_gain(legs)
    bes = breakevens(prices, expiry_pnl)

    prob_profit = _prob_profit_from_mc(symbol, legs)

    response = BsResponse(
        payoff_at_expiry=[BsPoint(price=float(p), pnl=float(v)) for p, v in zip(prices, expiry_pnl)],
        current_value=[BsPoint(price=float(p), pnl=float(v)) for p, v in zip(prices, cur_val)],
        cost_debit_credit=float(cost_basis(legs)),
        max_gain=None if unlimited_gain else float(np.max(expiry_pnl)),
        max_loss=None if unlimited_loss else float(np.min(expiry_pnl)),
        unlimited_gain=unlimited_gain,
        unlimited_loss=unlimited_loss,
        edge_pnl_low=float(expiry_pnl[0]),
        edge_pnl_high=float(expiry_pnl[-1]),
        breakevens=bes,
        greeks=BsGreeks(**greeks),
        prob_profit=prob_profit,
    )
    cache.set(cache_key, response, ttl_seconds=30)
    return response


def _hydrate_legs(
    legs_in: list[dict],
    chain,
    spot: float,
    today: date,
    rate: float,
    iv_override: float | None,
) -> list[Leg]:
    """Convert request legs to internal Leg objects with IV + premium pre-priced."""
    out: list[Leg] = []
    for spec in legs_in:
        try:
            expiry = date.fromisoformat(spec["expiry"])
        except (KeyError, ValueError):
            continue
        T = max((expiry - today).days / 365.0, 0.0)
        iv = iv_override or _leg_iv(chain, spec["strike"], expiry, spec["type"]) or _atm_iv_for_expiry(chain, spot, expiry)
        if iv is None:
            log.warning("no IV for leg %s; skipping", spec)
            continue
        premium = bs_price(spot, spec["strike"], T, rate, iv, spec["type"])
        out.append(
            Leg(
                strike=float(spec["strike"]),
                type=spec["type"],
                side=spec["side"],
                quantity=int(spec.get("quantity", 1)),
                iv=iv,
                T=T,
                premium=premium,
            )
        )
    return out


def _leg_iv(chain, strike: float, expiry: date, opt_type: str) -> float | None:
    for c in chain:
        if c.strike == strike and c.expiry == expiry and c.type == opt_type and c.iv is not None:
            return c.iv
    return None


def _atm_iv_for_expiry(chain, spot: float, expiry: date) -> float | None:
    same = [c for c in chain if c.expiry == expiry]
    if not same:
        return None
    atm = min({c.strike for c in same}, key=lambda k: abs(k - spot))
    ivs = [c.iv for c in same if c.strike == atm and c.iv is not None]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def _pick_far_expiry(chain, after: date) -> date | None:
    later = sorted({c.expiry for c in chain if c.expiry > after})
    return later[0] if later else None


def _prob_profit_from_mc(symbol: str, legs: list[Leg]) -> float | None:
    """P(payoff_at_expiry > 0) from MC's full terminal-price distribution.

    Pulls from the side-cached 10K terminal-prices array populated by
    run_mc() — never re-runs MC. If MC hasn't been called yet for this
    symbol, triggers it once (which then populates the side cache).
    """
    horizon = _resolve_default_horizon(symbol)
    terminals = get_cached_terminals(symbol)
    if terminals is None:
        try:
            run_mc(symbol, horizon=horizon)
        except HTTPException:
            return None
        terminals = get_cached_terminals(symbol)
    if terminals is None or terminals.size == 0:
        return None
    payoff = payoff_at_expiry(legs, terminals)
    return float(np.mean(payoff > 0))


def _legs_cache_key(legs_in, iv_override, rate_override) -> str:
    parts = [
        f"{leg['strike']}{leg['type'][0]}{leg['side'][0]}{leg.get('quantity', 1)}@{leg['expiry']}"
        for leg in legs_in
    ]
    return f"{','.join(parts)}|iv={iv_override}|r={rate_override}"
