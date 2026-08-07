"""Shared fill realism — deterministic spread-crossing slippage.

Extracted from routers/zerodte so EVERY fill in the sim pays the same
friction the user-facing market opens do (audit C4: monitor stop/limit
entries, bracket/trailing/premium exits, liquidations and /reverse
re-opens all previously filled at the frictionless mid, running the
sim's P&L structurally rich):

  * `fill_slippage` / `pick_fill_price` — the adverse half-spread +
    size-impact machinery (moved verbatim from routers/zerodte; the
    router re-exports them so its callers and tests are unchanged).
  * `close_friction` — the $ cost of crossing the spread to EXIT a
    position's legs at market, subtracted from the mid-based unrealized
    when a close is booked. Liquidations stress the size-impact term by
    `LIQUIDATION_STRESS` (a forced flatten is the most slippage-heavy
    fill there is).
  * `live_leg_quotes` / `leg_quote` — best-effort live two-sided quotes
    for a position's legs via alpaca_client.get_live_option_quotes.
    ANY failure (cold feed, missing contract) degrades to {} so callers
    fall back to the mid mark — an exit is never blocked on missing data.
  * `entry_touch_triggered` — touch-based (bid/ask) working-order
    triggers: a BUY limit is executable when the ASK trades through it,
    a SELL when the BID does; stops trigger on the adverse side. Returns
    None when no two-sided quote exists so callers keep the mid rule.

No RNG anywhere — a given quote + size always yields the same fill.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Per-contract size-impact slippage: each contract above the first nudges the
# fill a further 0.5% of mid against the trader, capped so a big clip can't run
# away. Deterministic (no RNG) so tests and replays are stable.
_SIZE_SLIP_PER_CONTRACT = 0.005   # 0.5% of mid per extra contract
_SIZE_SLIP_CAP = 0.05             # never worse than 5% of mid from size alone

# A liquidation is a STRESSED fill — the book is being flattened into whatever
# liquidity exists. The size-impact term is charged at this multiple.
LIQUIDATION_STRESS = 1.5


def fill_slippage(
    mid: float, spread: float, action: str, contracts: int, *, stress: float = 1.0
) -> float:
    """Deterministic adverse slippage added to (buy) / subtracted from (sell)
    the mid for a MARKET fill.

    Two components, both pushing AGAINST the trader:
      1. cross HALF the bid/ask spread (you don't get filled at mid — you give
         up half the spread to cross), and
      2. a size-impact term scaling with the clip size (each contract beyond
         the first adds 0.5% of mid, capped at 5%), multiplied by `stress`
         on a forced (liquidation) fill.

    Returns the signed price adjustment to apply (always ≥ 0 in magnitude;
    sign handled by the caller via `action`)."""
    half_spread = max(0.0, spread) / 2.0
    extra = max(0, int(contracts) - 1)
    size_frac = min(_SIZE_SLIP_CAP, extra * _SIZE_SLIP_PER_CONTRACT)
    return half_spread + mid * size_frac * stress


def pick_fill_price(
    q, action: str = "buy", contracts: int = 1, *, stress: float = 1.0
) -> float:
    """Indicative MARKET fill price with DETERMINISTIC slippage.

    `q` is any quote duck-type with .bid/.ask/.last. Reference mid comes from
    bid/ask (or last when one-sided). The trader never fills at the perfect
    mid: buyers pay mid + slippage, sellers receive mid − slippage, where
    slippage = half the spread + a size-impact term (see fill_slippage). No
    RNG, so a given quote+size always yields the same fill. Returns 0 if no
    usable quote at all — caller decides the fallback (503 on an open; the
    mid mark on a monitor fill). The result is floored at 0.01 so a
    wide-spread short can't fill at ≤ 0."""
    raw_bid = getattr(q, "bid", None)
    raw_ask = getattr(q, "ask", None)
    raw_last = getattr(q, "last", None)
    bid = float(raw_bid) if raw_bid and raw_bid > 0 else None
    ask = float(raw_ask) if raw_ask and raw_ask > 0 else None

    if bid is not None and ask is not None:
        if ask < bid:
            # Crossed/locked-through book (ask BELOW bid) — stale or erroneous
            # data. Its "mid" is meaningless and `max(0, ask − bid)` collapses
            # the spread to 0, which let a SELL fill at the fantasy mid (e.g.
            # bid 5.00 / ask 0.01 → sell at ~2.50 on a contract offered at a
            # penny). Treat as NO usable quote: the caller refuses the open
            # (503) or falls back to the model mid mark on a monitor fill.
            return 0.0
        mid = (bid + ask) / 2.0
        spread = max(0.0, ask - bid)
    elif raw_last and raw_last > 0:
        # One-sided/last-only: synthesize a nominal spread off last so size
        # impact still bites; assume a 2%-of-last touch spread.
        mid = float(raw_last)
        spread = mid * 0.02
    elif ask is not None:
        # Ask-only: synthesize a 2% touch BELOW the offer, so a market BUY pays
        # ~the ask (not below it) and a SELL is penalized — not a free fill at
        # the lone quote. (Previously spread=0 let a 1-lot buy fill at the ask
        # with zero slippage, and a sell receive the ask — impossibly good.)
        spread = ask * 0.02
        mid = ask - spread / 2.0
    elif bid is not None:
        # Bid-only: synthesize a 2% touch ABOVE the bid, so a market SELL hits
        # ~the bid and a BUY pays up — not a free fill at the lone quote.
        spread = bid * 0.02
        mid = bid + spread / 2.0
    else:
        return 0.0

    slip = fill_slippage(mid, spread, action, contracts, stress=stress)
    px = mid + slip if action == "buy" else mid - slip
    return max(0.01, round(px, 4))


def two_sided(q) -> tuple[float, float] | None:
    """(bid, ask) when the quote is genuinely two-sided, else None."""
    if q is None:
        return None
    bid = getattr(q, "bid", None)
    ask = getattr(q, "ask", None)
    if bid and ask and bid > 0 and ask > 0:
        return float(bid), float(ask)
    return None


def _leg_key(leg: dict) -> tuple[float, str] | None:
    strike = leg.get("strike")
    side = leg.get("side")
    if strike is None or side not in ("call", "put"):
        return None
    return (round(float(strike), 2), str(side))


def live_leg_quotes(symbol: str, legs: list[dict]) -> dict:
    """Live two-sided quotes for the given legs, keyed by (strike, side) —
    the alpaca_client.get_live_option_quotes contract (today's-expiry
    contracts; falls back to the chain snapshot internally; missing
    contracts are simply absent from the dict).

    Best-effort by design: ANY failure (feed cold, breaker open, binding not
    yet importable) returns {} so callers fall back to the mid mark — an
    exit is never blocked on missing data."""
    keys = sorted({k for k in (_leg_key(leg) for leg in legs or []) if k is not None})
    if not keys:
        return {}
    try:
        from services.alpaca_client import get_live_option_quotes
    except ImportError:  # binding not present — degrade to the mid mark
        return {}
    try:
        return get_live_option_quotes(symbol, keys) or {}
    except Exception:  # noqa: BLE001 — cold feed / breaker open → mid fallback
        log.debug("fills: live option quotes failed for %s", symbol)
        return {}


def leg_quote(quotes: dict, leg: dict):
    """The live quote for one leg out of a live_leg_quotes map, or None."""
    key = _leg_key(leg)
    return quotes.get(key) if key is not None else None


def close_friction(
    symbol: str, legs: list[dict], *, stressed: bool = False, quotes: dict | None = None
) -> float:
    """$ cost of CROSSING THE SPREAD to exit `legs` at market — subtracted
    from the mid-based unrealized when a close is booked.

    Per leg with a live two-sided quote: contracts × (half-spread +
    size-impact) × 100. Exiting is adverse whichever direction the leg is
    (a long sells to the bid side, a short buys to the ask side), so the
    friction is additive across legs. Legs without a two-sided quote
    contribute 0 (they exit at the mid mark — never block an exit on
    missing data). `stressed` charges the size-impact term at
    LIQUIDATION_STRESS (a forced flatten is the most slippage-heavy fill
    there is)."""
    if not legs:
        return 0.0
    if quotes is None:
        quotes = live_leg_quotes(symbol, legs)
    if not quotes:
        return 0.0
    stress = LIQUIDATION_STRESS if stressed else 1.0
    total = 0.0
    for leg in legs:
        ba = two_sided(leg_quote(quotes, leg))
        if ba is None:
            continue
        bid, ask = ba
        mid = (bid + ask) / 2.0
        contracts = int(leg.get("contracts", 1) or 1)
        slip = fill_slippage(mid, ask - bid, "sell", contracts, stress=stress)
        total += contracts * slip * 100.0
    return round(total, 2)


def entry_touch_triggered(
    order_type: str, action: str, trigger: float, q
) -> bool | None:
    """Touch-based working-order trigger against a live two-sided quote.

    A BUY limit is executable when the ASK trades through it (ask ≤ limit);
    a SELL limit when the BID does (bid ≥ limit). Stops trigger on the
    ADVERSE side touching the stop: buy-stop on the ask, sell-stop on the
    bid. Returns None when the quote isn't two-sided so the caller falls
    back to the mid rule (never blocks on missing data)."""
    ba = two_sided(q)
    if ba is None:
        return None
    bid, ask = ba
    if order_type == "limit":
        return ask <= trigger if action == "buy" else bid >= trigger
    # stop
    return ask >= trigger if action == "buy" else bid <= trigger
