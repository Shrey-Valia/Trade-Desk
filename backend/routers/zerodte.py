"""ZERO-DTE — chain lookup and paper-open.

  GET  /api/zerodte/chain?symbol=  ATM call+put for the symbol expiring today
  POST /api/zerodte/open            create a paper long_straddle Trade record
  POST /api/zerodte/open-leg        create a single-leg paper Trade

The FRONT-END drives 0DTE through the existing position pipeline: /open
creates a Trade, and the chart's analytics endpoint
(/api/journal/trades/{id}/analytics) polls for the live mark and intraday
breakevens.

Intraday BS math lives in calculations/intraday_analytics — shared with
the journal router's 0DTE branch. The engine file (black_scholes.py)
remains frozen.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from calculations.intraday_analytics import (
    SECONDS_PER_YEAR,
    bs_intraday,
    compute_contract_preview,
    greeks_intraday,
    iv_intraday,
)
from calculations.position_analytics import DEFAULT_IV
from config import settings
from database import get_session
from models.combine import Combine
from models.trade import Trade
from schemas.journal import TradeLeg, TradeOut, compute_net_debit_credit
from services.alpaca_client import get_chain_snapshot, get_quotes
from services.auth import get_active_combine
from services.combine_state import combine_snapshot
from services.copy_trade import mirror_close, mirror_open
from services.fred_client import DEFAULT_RATE_FALLBACK, latest_dgs3mo_rate
from services.market_calendar import is_market_open

router = APIRouter(prefix="/api/zerodte", tags=["zerodte"])
log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
# US equity options expire at 4:00pm ET. SPY/SPX have a 4:15pm AM-settle
# convention but for paper-prototype purposes 4:00pm matches "the session".
_CLOSE_HHMM = (16, 0)


# ---------------------------------------------------------------------------
# Session-clock helpers
# ---------------------------------------------------------------------------


def _session_close_et(reference: datetime | None = None) -> datetime:
    """The session close for the reference date — 4:00pm ET, or the 1:00pm ET
    early close on NYSE half-days (half-day aware via the schedule), with a flat
    4pm fallback for non-trading days. If today's close has passed (after-hours,
    weekends) we still anchor to TODAY's close so the prototype clock is
    well-defined — the scrubber just starts in the 'expired' state. Routing
    through the NYSE schedule stops ~9 half-days/year from being priced with
    ~3 extra hours of fictitious time value."""
    from services.market_calendar import session_close_et as _sched_close

    now = reference or datetime.now(_ET)
    close = _sched_close(now.date().isoformat())
    if close is not None:
        return close
    return datetime.combine(now.date(), time(*_CLOSE_HHMM), tzinfo=_ET)


def _t_years_to_close(at: datetime | None = None) -> float:
    """Years remaining from `at` (or now) to today's 4pm ET. Floored
    at 1 minute (1/525,600 year) so BS never sees T<=0; we'd rather
    show a nearly-vertical kink than a divide-by-zero blow-up."""
    now = at or datetime.now(_ET)
    seconds = (_session_close_et(now) - now).total_seconds()
    seconds = max(seconds, 60.0)  # 1-minute floor
    return seconds / SECONDS_PER_YEAR


# ---------------------------------------------------------------------------
# Chain endpoint — find today's SPY ATM call + put
# ---------------------------------------------------------------------------


class _LegQuote(BaseModel):
    symbol: str
    strike: float
    side: Literal["call", "put"]
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    iv: float | None = None


class ChainOut(BaseModel):
    underlying: str = "SPY"
    spot: float
    expiry: str                       # ISO date
    strike: float                     # ATM strike
    call: _LegQuote
    put: _LegQuote
    t_years_to_close: float           # remaining (years)
    session_close_iso: str            # ISO datetime ET
    indicative: bool = True
    notice: str = "Paper · indicative pricing (approximate)"


class ChainStrikeRow(BaseModel):
    """One row of the chain table — strike with call+put prices + OI.
    `call_price` / `put_price` come from the live indicative quote where
    available, else a BS-model fallback at the ATM-implied IV. `source`
    on each side is "quote" | "bs" so the UI can subtly mark fallbacks."""

    strike: float
    call_price: float
    call_source: Literal["quote", "bs"]
    call_open_interest: int | None = None
    put_price: float
    put_source: Literal["quote", "bs"]
    put_open_interest: int | None = None
    # Raw two-sided quote + today's per-contract volume, straight off the
    # chain snapshot. None when the feed has no quote/volume for the side.
    call_bid: float | None = None
    call_ask: float | None = None
    call_volume: int | None = None
    put_bid: float | None = None
    put_ask: float | None = None
    put_volume: int | None = None
    is_atm: bool = False
    # Per-share greeks (display-only, at-a-glance on the chain). Computed
    # from the EXISTING bs_greeks engine at the ATM-implied IV — same
    # inputs (spot, strike, T-to-close, rate, iv) as the BS price fallback.
    # delta is unitless; theta is per-day (the engine divides by 365).
    call_delta: float = 0.0
    call_theta: float = 0.0
    put_delta: float = 0.0
    put_theta: float = 0.0


class ChainTableOut(BaseModel):
    underlying: str
    spot: float
    expiry: str
    atm_strike: float
    iv_used: float                    # the IV that drives BS fallbacks
    iv_source: Literal["implied_atm", "default"]
    rows: list[ChainStrikeRow]
    t_years_to_close: float
    session_close_iso: str
    # Freshest observation timestamp behind this snapshot (ISO-8601) — the
    # max of the underlying quote's trade stamp and the contracts' last-trade
    # stamps. None when the feed omits timestamps entirely.
    as_of: str | None = None
    indicative: bool = True
    notice: str = "Paper · indicative pricing (approximate)"


def _require_fresh_spot(quote) -> None:
    """Refuse to open against a STALE underlying print. A halted or thinly
    traded symbol can show a last trade minutes old even during the session, and
    filling against it books a price the market isn't actually at. No-op when
    the feed omits a trade timestamp (can't judge → let it through)."""
    as_of = getattr(quote, "as_of", None)
    if as_of is None:
        return
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - as_of).total_seconds()
    if age > settings.max_spot_staleness_s:
        raise HTTPException(
            503,
            f"Underlying quote is stale ({int(age)}s old) — the symbol may be halted "
            "or illiquid. Try again when it is trading.",
        )


def _resolve_atm_chain(symbol: str) -> tuple[str, float, date, float, _LegQuote, _LegQuote]:
    """Find the ATM call+put for the given symbol expiring today (or the
    nearest available expiry if 0DTE isn't listed). Returns
    (symbol, spot, expiry_date, atm_strike, call_quote, put_quote).
    Raises HTTPException with a 503 on any data-availability failure."""
    sym = symbol.upper().strip()
    chain = get_chain_snapshot(sym, with_volume=False)
    if not chain:
        raise HTTPException(503, f"{sym} options chain unavailable")
    quote = get_quotes([sym]).get(sym)
    if quote is None:
        raise HTTPException(503, f"{sym} quote unavailable")
    _require_fresh_spot(quote)
    spot = float(quote.price)

    today = datetime.now(_ET).date()
    same_day = [c for c in chain if c.expiry == today]
    if not same_day:
        future = sorted({c.expiry for c in chain if c.expiry >= today})
        if not future:
            raise HTTPException(503, f"No usable expiry for {sym}")
        target_expiry = future[0]
        same_day = [c for c in chain if c.expiry == target_expiry]
    else:
        target_expiry = today

    strikes = sorted({c.strike for c in same_day})
    atm = min(strikes, key=lambda k: abs(k - spot))

    def pick(opt_type: Literal["call", "put"]) -> _LegQuote:
        match = next((c for c in same_day if c.strike == atm and c.type == opt_type), None)
        if match is None:
            raise HTTPException(503, f"No {opt_type} at ATM strike {atm}")
        return _LegQuote(
            symbol=f"{sym} {target_expiry.isoformat()} {atm:g}{opt_type[0].upper()}",
            strike=atm,
            side=opt_type,
            bid=match.bid,
            ask=match.ask,
            last=match.last,
            iv=match.iv,
        )

    return sym, spot, target_expiry, atm, pick("call"), pick("put")


@router.get("/chain", response_model=ChainOut)
def get_atm_chain(symbol: str = "SPY") -> ChainOut:
    """ATM call+put for `symbol` expiring TODAY (or nearest expiry).

    Single-strike payload kept for the legacy ZeroDtePage; the chart
    view uses /chain/table for the windowed grid."""
    sym, spot, target_expiry, atm, call_q, put_q = _resolve_atm_chain(symbol)
    return ChainOut(
        underlying=sym,
        spot=spot,
        expiry=target_expiry.isoformat(),
        strike=atm,
        call=call_q,
        put=put_q,
        t_years_to_close=_t_years_to_close(),
        session_close_iso=_session_close_et().isoformat(),
    )


def _quote_price(c) -> tuple[float | None, str]:
    """Best per-share price from a ContractRow. Returns (price, source).
    source is "mid"/"ask"/"last" — only used internally; the API
    surfaces "quote" vs "bs" externally.

    Prefer the (bid+ask)/2 MID when two-sided; only fall back to a lone ask
    (then last) when there's no two-sided market. Previously the ask branch ran
    first, so the mid branch was dead code and every quoted premium was the
    offer — biasing displayed premiums and the back-solved ATM IV upward."""
    if c.bid and c.ask and c.bid > 0 and c.ask > 0:
        return (float(c.bid) + float(c.ask)) / 2, "mid"
    if c.ask and c.ask > 0:
        return float(c.ask), "ask"
    if c.last and c.last > 0:
        return float(c.last), "last"
    return None, "none"


@router.get("/chain/table", response_model=ChainTableOut)
def get_chain_table(
    symbol: str = "SPY",
    strikes: int = 15,
) -> ChainTableOut:
    """A WINDOWED chain table for the trading-ticket UI.

    Returns ±`strikes` strikes around the at-the-money strike with
    call/put prices and open interest per row. Where a live indicative
    quote isn't available, prices are filled by Black-Scholes against
    the ATM-implied IV (intraday floor) — flagged via call_source /
    put_source so the UI can mark fallbacks.

    Performance: the underlying chain snapshot is already cached 5min
    in alpaca_client; the windowing + BS fallback here is O(strikes)
    so the endpoint adds ~1ms on a warm cache. `with_volume=True` so the
    per-strike volume columns carry real data — the ticker page fetches
    the same cache key, so the expensive bars pass is typically warm."""
    sym = symbol.upper().strip()
    chain = get_chain_snapshot(sym, with_volume=True)
    if not chain:
        raise HTTPException(503, f"{sym} options chain unavailable")
    quote = get_quotes([sym]).get(sym)
    if quote is None:
        raise HTTPException(503, f"{sym} quote unavailable")
    spot = float(quote.price)

    # Strict 0DTE: chain table refuses to fall back to the nearest
    # future expiry. Showing a non-0DTE chain would let the user click
    # a strike and then 409 — confusing. The UI listens for this 409
    # detail and renders a clean "No 0DTE for {SYMBOL} today" message
    # with the open buttons disabled.
    today = datetime.now(_ET).date()
    same_day = [c for c in chain if c.expiry == today]
    if not same_day:
        raise HTTPException(
            status_code=409,
            detail=f"No 0DTE for {sym} today ({today.isoformat()}).",
        )
    target_expiry = today

    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = DEFAULT_RATE_FALLBACK
    t_close = _t_years_to_close()

    all_strikes = sorted({c.strike for c in same_day})
    if not all_strikes:
        raise HTTPException(503, f"No strikes for {sym} at {target_expiry}")
    atm = min(all_strikes, key=lambda k: abs(k - spot))
    atm_idx = all_strikes.index(atm)

    half = max(1, strikes)
    lo = max(0, atm_idx - half)
    hi = min(len(all_strikes), atm_idx + half + 1)
    window = all_strikes[lo:hi]

    by_key: dict[tuple[float, str], object] = {}
    for c in same_day:
        by_key[(c.strike, c.type)] = c

    # ATM-implied IV: try the ATM call and put; median when both work.
    iv_used: float = DEFAULT_IV
    iv_source: Literal["implied_atm", "default"] = "default"
    atm_call = by_key.get((atm, "call"))
    atm_put = by_key.get((atm, "put"))
    iv_candidates: list[float] = []
    for c in (atm_call, atm_put):
        if c is None:
            continue
        px, _ = _quote_price(c)
        if px is None:
            continue
        side = c.type  # type: ignore[attr-defined]
        iv = iv_intraday(px, spot, atm, t_close, rate, side)
        if iv is not None:
            iv_candidates.append(iv)
    if iv_candidates:
        iv_used = sum(iv_candidates) / len(iv_candidates)
        iv_source = "implied_atm"

    rows: list[ChainStrikeRow] = []
    for k in window:
        call = by_key.get((k, "call"))
        put = by_key.get((k, "put"))

        call_px, _ = (_quote_price(call) if call else (None, "none"))
        if call_px is None or call_px <= 0:
            call_px = bs_intraday(spot, k, t_close, rate, iv_used, "call")
            call_source: Literal["quote", "bs"] = "bs"
        else:
            call_source = "quote"

        put_px, _ = (_quote_price(put) if put else (None, "none"))
        if put_px is None or put_px <= 0:
            put_px = bs_intraday(spot, k, t_close, rate, iv_used, "put")
            put_source: Literal["quote", "bs"] = "bs"
        else:
            put_source = "quote"

        # Display greeks via the INTRADAY engine (1-minute T floor), matching
        # the bs_intraday prices in the same rows. Using the day-floored
        # bs_greeks here contradicted the price — it computed delta/theta as if
        # a full trading day remained, hiding the violent end-of-day 0DTE decay.
        cg = greeks_intraday(spot, k, t_close, rate, iv_used, "call")
        pg = greeks_intraday(spot, k, t_close, rate, iv_used, "put")

        rows.append(
            ChainStrikeRow(
                strike=k,
                call_price=round(float(call_px), 4),
                call_source=call_source,
                call_open_interest=getattr(call, "open_interest", None) if call else None,
                put_price=round(float(put_px), 4),
                put_source=put_source,
                put_open_interest=getattr(put, "open_interest", None) if put else None,
                call_bid=getattr(call, "bid", None) if call else None,
                call_ask=getattr(call, "ask", None) if call else None,
                call_volume=getattr(call, "volume", None) if call else None,
                put_bid=getattr(put, "bid", None) if put else None,
                put_ask=getattr(put, "ask", None) if put else None,
                put_volume=getattr(put, "volume", None) if put else None,
                is_atm=(k == atm),
                call_delta=round(cg["delta"], 4),
                call_theta=round(cg["theta"], 4),
                put_delta=round(pg["delta"], 4),
                put_theta=round(pg["theta"], 4),
            )
        )

    return ChainTableOut(
        underlying=sym,
        spot=spot,
        expiry=target_expiry.isoformat(),
        atm_strike=atm,
        iv_used=iv_used,
        iv_source=iv_source,
        rows=rows,
        t_years_to_close=t_close,
        session_close_iso=_session_close_et().isoformat(),
        as_of=_chain_as_of(quote, same_day),
    )


def _chain_as_of(quote, contract_rows) -> str | None:
    """Freshest observation timestamp behind a chain payload — the underlying
    quote's trade stamp and each contract's last-trade stamp, max'd (naive
    stamps assumed UTC). None when the feed omits timestamps entirely, so the
    client can render an explicit 'age unknown' instead of a fake freshness."""
    stamps = [getattr(quote, "as_of", None)]
    stamps.extend(getattr(r, "as_of", None) for r in contract_rows)
    aware = [
        s.replace(tzinfo=UTC) if s.tzinfo is None else s
        for s in stamps
        if s is not None
    ]
    return max(aware).isoformat() if aware else None


# ---------------------------------------------------------------------------
# Open endpoint — create a paper long_straddle Trade and return it
# ---------------------------------------------------------------------------


class OpenRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=16, default="SPY")
    contracts: int = Field(gt=0, le=100, default=1)
    # buy = long straddle (debit); sell = short straddle (credit). Same
    # strike/expiry on both legs either way.
    action: Literal["buy", "sell"] = "buy"
    # Optional SL/TP brackets pre-attached at entry (underlying price levels).
    # The straddle quick-entry is always a MARKET fill; only the brackets are
    # optional here.
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    # Premium-denominated TP/SL (Tastytrade "manage winners") — see
    # _validate_premium_mults for the direction-dependent bands.
    tp_premium_mult: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Take-profit multiple of |net entry premium|. NET-DEBIT (buy):"
            " close when the mark reaches entry × mult (must be > 1)."
            " NET-CREDIT (sell) the semantics INVERT: the FRACTION of the"
            " collected credit to buy back at (0 < mult < 1; 0.5 = close at"
            " 50% of max profit)."
        ),
    )
    sl_premium_mult: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Stop-loss multiple of |net entry premium|. NET-DEBIT (buy):"
            " close when the mark decays to entry × mult (0 < mult < 1)."
            " NET-CREDIT (sell): the cut multiple of the credit (must be"
            " > 1; 2.0 = stop when the mark reaches 2× the credit)."
        ),
    )


class OpenLegRequest(BaseModel):
    """Click-to-open from the chain table: a single call/put leg at the
    given strike, expiring today. `action` is buy (long) or sell (short).

    order_type="market" (default) fills immediately at the SERVER-priced
    live chain quote (mid + deterministic slippage — the same machinery the
    straddle path uses); `entry_price` is DISPLAY-ONLY and ignored (kept for
    API compat — trusting the click-time price let a trader book a stale
    premium as instant edge). order_type="limit"/"stop" places a WORKING
    order — `limit_price` is the OPTION-premium trigger the monitor fills
    against. order_type="stop_limit" ARMS at `stop_price` (mark crosses it)
    then RESTS as a limit at `limit_price`. Optional stop_loss/take_profit
    are UNDERLYING price levels (the draggable chart brackets)."""

    symbol: str = Field(min_length=1, max_length=16)
    side: Literal["call", "put"]
    action: Literal["buy", "sell"] = "buy"
    strike: float = Field(gt=0)
    # DEPRECATED / IGNORED — market fills are priced server-side (see class
    # docstring). Retained so older clients still validate.
    entry_price: float = Field(ge=0, default=0.0)
    contracts: int = Field(gt=0, le=100, default=1)
    order_type: Literal["market", "limit", "stop", "stop_limit"] = "market"
    limit_price: float | None = Field(default=None, gt=0)
    # stop_limit: the OPTION-premium level the order arms at (then rests as a
    # limit at limit_price). Required for stop_limit; ignored otherwise.
    stop_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    # Trailing stop (EXIT) attached at open — trails the favorable OPTION mark
    # by trail_amount ($/share) or trail_pct (0.10 = 10%). The monitor advances
    # the high-water and stops the position out when the mark retraces past it.
    trail_amount: float | None = Field(default=None, gt=0)
    trail_pct: float | None = Field(default=None, gt=0, le=1)
    # OCO pairing: two working orders sharing this id are siblings — when one
    # fills, the monitor cancels the other. None = unpaired.
    oco_group: str | None = Field(default=None, max_length=36)
    # Time-in-force for a WORKING order: "gtc" rests until filled/cancelled,
    # "day" is cancelled by the monitor if it survives unfilled into a later
    # session. Ignored for market orders. Defaults to "gtc".
    time_in_force: Literal["day", "gtc"] = "gtc"
    # Premium-denominated TP/SL (Tastytrade "manage winners") — see
    # _validate_premium_mults for the direction-dependent bands.
    tp_premium_mult: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Take-profit multiple of |net entry premium|. NET-DEBIT (buy):"
            " close when the mark reaches entry × mult (must be > 1)."
            " NET-CREDIT (sell) the semantics INVERT: the FRACTION of the"
            " collected credit to buy back at (0 < mult < 1; 0.5 = close at"
            " 50% of max profit)."
        ),
    )
    sl_premium_mult: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Stop-loss multiple of |net entry premium|. NET-DEBIT (buy):"
            " close when the mark decays to entry × mult (0 < mult < 1)."
            " NET-CREDIT (sell): the cut multiple of the credit (must be"
            " > 1; 2.0 = stop when the mark reaches 2× the credit)."
        ),
    )


# Per-contract size-impact slippage: each contract above the first nudges the
# fill a further 0.5% of mid against the trader, capped so a big clip can't run
# away. Deterministic (no RNG) so tests and replays are stable.
_SIZE_SLIP_PER_CONTRACT = 0.005   # 0.5% of mid per extra contract
_SIZE_SLIP_CAP = 0.05             # never worse than 5% of mid from size alone


def _fill_slippage(mid: float, spread: float, action: str, contracts: int) -> float:
    """Deterministic adverse slippage added to (buy) / subtracted from (sell)
    the mid for a MARKET fill.

    Two components, both pushing AGAINST the trader:
      1. cross HALF the bid/ask spread (you don't get filled at mid — you give
         up half the spread to cross), and
      2. a size-impact term scaling with the clip size (each contract beyond
         the first adds 0.5% of mid, capped at 5%).

    Returns the signed price adjustment to apply (always ≥ 0 in magnitude;
    sign handled by the caller via `action`)."""
    half_spread = max(0.0, spread) / 2.0
    extra = max(0, int(contracts) - 1)
    size_frac = min(_SIZE_SLIP_CAP, extra * _SIZE_SLIP_PER_CONTRACT)
    return half_spread + mid * size_frac


def _pick_fill_price(q: _LegQuote, action: str = "buy", contracts: int = 1) -> float:
    """Indicative MARKET fill price with DETERMINISTIC slippage.

    Reference mid comes from bid/ask (or last when one-sided). The trader never
    fills at the perfect mid: buyers pay mid + slippage, sellers receive
    mid − slippage, where slippage = half the spread + a size-impact term
    (see _fill_slippage). No RNG, so a given quote+size always yields the same
    fill. Returns 0 if no usable quote at all — caller turns that into a 503.
    The result is floored at 0.01 so a wide-spread short can't fill at ≤ 0."""
    bid = float(q.bid) if q.bid and q.bid > 0 else None
    ask = float(q.ask) if q.ask and q.ask > 0 else None

    if bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
        spread = max(0.0, ask - bid)
    elif q.last and q.last > 0:
        # One-sided/last-only: synthesize a nominal spread off last so size
        # impact still bites; assume a 2%-of-last touch spread.
        mid = float(q.last)
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

    slip = _fill_slippage(mid, spread, action, contracts)
    px = mid + slip if action == "buy" else mid - slip
    return max(0.01, round(px, 4))


def _require_market_open() -> None:
    """Reject opens when the NYSE session is not OPEN. 0DTE contracts
    bought during a closed session have zero (or near-zero) time value
    and would render as dead lines on the chart — the engine and the
    UX both fail soft. Block the door instead."""
    if not is_market_open():
        raise HTTPException(
            status_code=409,
            detail=(
                "Market closed — 0DTE positions can only be opened during "
                "the regular session (09:30 – 16:00 ET, Mon–Fri)."
            ),
        )


def _open_contracts_for_combine(session: Session, combine_id: int) -> int:
    """Total contracts across the combine's currently-OPEN and WORKING
    positions. The scaling cap limits simultaneous open size, so a new order
    is checked against this aggregate — not just its own size. Without this a
    trader could stack multiple max-size orders past the cap (e.g. four 1-lots
    when the cap is 2). Working (resting) orders count too, so you can't queue
    past the cap and have them fill later."""
    rows = (
        session.execute(
            select(Trade).where(
                Trade.combine_id == combine_id,
                Trade.status.in_(("open", "working")),
            )
        )
        .scalars()
        .all()
    )
    total = 0
    for t in rows:
        legs = t.legs or []
        # TOTAL option contracts across all legs (per-leg-per-contract) — a real
        # prop firm counts a 5-lot straddle as 10 contracts, not 5. (Was max-leg,
        # which undercounted true open exposure for any multi-leg structure.)
        total += sum(int(leg.get("contracts", 1) or 1) for leg in legs)
    return total


# ── WS5: server-side contract clamping (folded from WS3) ────────────────────
def _clamp_contracts_to_cap(
    session: Session, combine: Combine, requested: int
) -> int:
    """Defense-in-depth size clamp. `_require_tradeable` already REJECTS an
    over-cap request with a 422, but this clamps the per-order size to the
    remaining scaling-plan capacity as a belt-and-suspenders guard so a leg
    can never be persisted above the cap even if the gate is bypassed or the
    snapshot shifts under us. Returns the size to actually use (>=1).

    The cap is per-COMBINE aggregate: remaining = max_contracts − already-open.
    With nothing open and a cap of N this is a no-op (returns `requested`)."""
    snap = combine_snapshot(session, combine)
    open_now = _open_contracts_for_combine(session, combine.id)
    remaining = max(0, snap.max_contracts - open_now)
    # Never clamp below 1 — a 0-contract order is meaningless; the reject path
    # in _require_tradeable owns the "no room at all" case (open_now >= cap).
    return max(1, min(int(requested), remaining)) if remaining > 0 else int(requested)
# ── end WS5 ─────────────────────────────────────────────────────────────────


def _live_combine_urpl(session: Session, combine: Combine) -> float:
    """Live mark-to-market URPL of the combine's OPEN positions. Best-effort and
    fully resilient: any pricing failure (cold feed / circuit open / no creds)
    contributes 0, so the order-time gate degrades to the realized-only check
    rather than blocking wrongly. The ~20s monitor + auto-liquidation remain the
    hard backstop."""
    try:
        open_trades = (
            session.execute(
                select(Trade).where(
                    Trade.combine_id == combine.id, Trade.status == "open"
                )
            )
            .scalars()
            .all()
        )
    except Exception:  # noqa: BLE001
        return 0.0
    if not open_trades:
        return 0.0
    from services.order_monitor import _default_unrealized_for

    now = datetime.now(UTC)
    total = 0.0
    spot_cache: dict[str, float | None] = {}
    for t in open_trades:
        try:
            if t.symbol not in spot_cache:
                spot_cache[t.symbol] = _spot_for_symbol(t.symbol)
            spot = spot_cache[t.symbol]
            if spot is None:
                continue
            total += _default_unrealized_for(t, spot, now)
        except Exception:  # noqa: BLE001 — one unpriceable trade contributes 0
            continue
    return total


def _require_tradeable(
    session: Session, combine: Combine, contracts: int | None = None
) -> None:
    """Enforce the combine's standing rules on the OPEN path — the rule
    actually binds server-side, not just via the trade-ticket soft-gate.
    Blocks a FAILED eval (MLL floor breached; must be reset) and a DAY
    LOCK (today's DLL hit; lifts at the 5pm-PT settlement). A PASSED /
    funded account is NOT blocked — it keeps trading to accrue payout.
    When `contracts` is given, also enforces the SCALING PLAN: the
    requested size can't exceed the max allowed at the current built
    equity (fixed intraday; re-evaluates at the 5pm-PT settlement).
    Computing the snapshot here also persists any pending settlement."""
    snap = combine_snapshot(session, combine)
    if snap.outcome == "failed":
        raise HTTPException(
            status_code=403,
            detail="Combine FAILED — the MLL floor was breached. Reset the evaluation to trade again.",
        )
    if snap.day_locked:
        if getattr(snap, "profit_locked", False):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Profit target reached — day protected. No further trading"
                    " today; the lock lifts at the 5pm-PT settlement."
                ),
            )
        raise HTTPException(
            status_code=403,
            detail="Daily loss limit hit — no further trading today. The day-lock lifts at the 5pm-PT settlement.",
        )
    # Realized-balance MLL gate, no open book required. A funded (passed)
    # account keeps its recorded outcome, so a realized balance already
    # at/through the MLL floor never flips snap.outcome to "failed" — without
    # this it could re-open a fresh position every tick with the floor gone.
    if snap.balance <= snap.mll:
        raise HTTPException(
            status_code=403,
            detail="Balance is at/through the MLL floor — the account cannot open new positions.",
        )
    # Mark-to-market gate: the realized-only snapshot above can read "tradeable"
    # while the LIVE balance (incl. open-position URPL) is already through the
    # MLL floor or has exhausted today's DLL budget. The ~20s monitor would
    # auto-liquidate, but don't let a fresh open slip in ahead of it. Only losses
    # can newly breach a floor the realized check already passed.
    urpl = _live_combine_urpl(session, combine)
    if urpl < 0:
        if snap.balance + urpl <= snap.mll:
            raise HTTPException(
                status_code=403,
                detail="Live balance is at/through the MLL floor from open-position losses — close positions before opening more.",
            )
        if not snap.dll_disabled and (snap.dll_used + (-urpl)) >= snap.dll_budget:
            raise HTTPException(
                status_code=403,
                detail="Daily loss limit reached on a mark-to-market basis (open-position losses) — no further trading today.",
            )
    if contracts is not None:
        open_now = _open_contracts_for_combine(session, combine.id)
        if open_now + contracts > snap.max_contracts:
            plural = "s" if snap.max_contracts != 1 else ""
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Scaling plan: max {snap.max_contracts} contract{plural} open "
                    f"at once at your current balance — you already have {open_now} "
                    f"open and requested {contracts}. Close a position or build "
                    "equity to scale up; the limit re-evaluates at the 5pm-PT "
                    "settlement."
                ),
            )


# SL/TP brackets must sit at least this far from the current underlying —
# the simulated analog of Topstep's "min 4 ticks from entry" guard, so a
# bracket can't be placed effectively on top of spot and insta-trigger.
MIN_BRACKET_FRAC = 0.001  # 0.1% of spot


def _validate_brackets(
    spot: float, stop_loss: float | None, take_profit: float | None
) -> None:
    """Reject SL/TP levels placed within MIN_BRACKET_FRAC of the underlying.
    Side (above/below) is intentionally NOT constrained — the monitor derives
    trigger direction from the fill price — but a level on top of spot would
    fire instantly, so guard the minimum distance."""
    min_dist = max(spot * MIN_BRACKET_FRAC, 0.01)
    for label, level in (("stop_loss", stop_loss), ("take_profit", take_profit)):
        if level is not None and abs(level - spot) < min_dist:
            raise HTTPException(
                422,
                f"{label} {level:.2f} is too close to the underlying "
                f"{spot:.2f} (min {min_dist:.2f} away).",
            )


def _validate_premium_mults(
    is_credit: bool, tp: float | None, sl: float | None
) -> None:
    """Direction-aware sanity check on the premium TP/SL multiples (400s).

    NET-DEBIT (long premium): tp > 1 (profit = premium expands) and
    0 < sl < 1 (stop = premium decays). NET-CREDIT (short premium) the
    semantics INVERT: tp is the fraction of the credit to buy back at
    (0 < tp < 1, e.g. 0.5 = close at 50% of max profit) and sl is the cut
    multiple (sl > 1, e.g. 2.0 = stop at 2× the credit)."""
    if tp is None and sl is None:
        return
    if is_credit:
        if tp is not None and not (0.0 < tp < 1.0):
            raise HTTPException(
                400,
                "tp_premium_mult must be between 0 and 1 for a net-credit"
                " position — the fraction of the collected credit to buy back"
                " at (e.g. 0.5 = close at 50% of max profit).",
            )
        if sl is not None and sl <= 1.0:
            raise HTTPException(
                400,
                "sl_premium_mult must be > 1 for a net-credit position — the"
                " multiple of the credit to cut at (e.g. 2.0).",
            )
    else:
        if tp is not None and tp <= 1.0:
            raise HTTPException(
                400,
                "tp_premium_mult must be > 1 for a net-debit position — the"
                " multiple of the entry premium to take profit at (e.g. 2.0).",
            )
        if sl is not None and not (0.0 < sl < 1.0):
            raise HTTPException(
                400,
                "sl_premium_mult must be between 0 and 1 for a net-debit"
                " position — the fraction of the entry premium to stop at"
                " (e.g. 0.5).",
            )


def _require_today_expiry(target_expiry: date) -> None:
    """0DTE-only rule: the contract must expire TODAY. Earlier the chain
    fallback picked the nearest future expiry when 0DTE wasn't listed;
    that path is closed here — better to refuse than open a multi-day
    position from a 0DTE-only screen."""
    today = datetime.now(_ET).date()
    if target_expiry != today:
        raise HTTPException(
            status_code=409,
            detail=(
                f"0DTE-only: no contracts expire today ({today.isoformat()}). "
                "Try another symbol or wait for tomorrow's session."
            ),
        )


@router.post("/open", response_model=TradeOut, status_code=201)
def open_zerodte_straddle(
    payload: OpenRequest,
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Open an ATM straddle on `symbol` expiring TODAY as a paper Trade.

    Direction:
      * action="buy"  → long straddle (debit) — profit on big move
      * action="sell" → short straddle (credit) — profit on stay-put

    Strict 0DTE — refuses to open if today's expiry isn't listed.
    Refuses to open if the NYSE session is not OPEN."""
    _require_market_open()
    # buy = net debit, sell = net credit — validate the premium TP/SL bands
    # per direction before any pricing work.
    _validate_premium_mults(
        payload.action == "sell", payload.tp_premium_mult, payload.sl_premium_mult
    )
    # A straddle is TWO legs, so it consumes 2× the per-leg size against the
    # total-contract cap. Gate and clamp on that effective total, then back out
    # the per-leg size. (Defense-in-depth: _require_tradeable already 422s an
    # over-cap request; the clamp guards a snapshot shift under us.)
    _require_tradeable(session, combine, contracts=payload.contracts * 2)
    allowed_total = _clamp_contracts_to_cap(session, combine, payload.contracts * 2)
    contracts = max(1, allowed_total // 2)
    sym, spot, expiry, atm, call_q, put_q = _resolve_atm_chain(payload.symbol)
    _require_today_expiry(expiry)

    action = payload.action
    call_price = _pick_fill_price(call_q, action, contracts)
    put_price = _pick_fill_price(put_q, action, contracts)
    if call_price == 0 or put_price == 0:
        raise HTTPException(503, f"{sym} indicative quotes unavailable at ATM {atm}")
    _validate_brackets(spot, payload.stop_loss, payload.take_profit)
    legs_json: list[dict] = [
        {
            "side": "call",
            "action": action,
            "strike": atm,
            "expiry": expiry.isoformat(),
            "contracts": contracts,
            "entry_price": round(call_price, 4),
        },
        {
            "side": "put",
            "action": action,
            "strike": atm,
            "expiry": expiry.isoformat(),
            "contracts": contracts,
            "entry_price": round(put_price, 4),
        },
    ]
    from schemas.journal import TradeLeg
    typed_legs = [TradeLeg(**leg) for leg in legs_json]
    net = compute_net_debit_credit(typed_legs)

    strategy = "long_straddle" if action == "buy" else "short_straddle"
    notes = (
        "0DTE long straddle · indicative fill"
        if action == "buy"
        else "0DTE short straddle · indicative credit"
    )

    trade = Trade(
        symbol=sym,
        strategy=strategy,
        entry_date=datetime.now(UTC),
        entry_underlying_price=spot,
        net_debit_credit=net,
        status="open",
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        tp_premium_mult=payload.tp_premium_mult,
        sl_premium_mult=payload.sl_premium_mult,
        is_paper=True,
        notes=notes,
        tier=combine.tier,
        combine_id=combine.id,
    )
    trade.legs = legs_json
    trade.tags = ["0dte"]
    trade.mistake_tags = []
    session.add(trade)
    session.commit()
    session.refresh(trade)

    # Copy trading: mirror to follower combines if this is the lead (best-effort).
    mirror_open(session, combine, trade)

    return _trade_to_out(trade)


@router.post("/open-leg", response_model=TradeOut, status_code=201)
def open_zerodte_leg(
    payload: OpenLegRequest,
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Open a single call OR put leg expiring TODAY at `strike`.

    Direction:
      * action="buy"  → long_call / long_put     (debit, pay premium)
      * action="sell" → short_call / short_put   (credit, collect premium)

    Strict 0DTE: today's expiry must be listed for `symbol`. Refuses to
    open if the NYSE session is not OPEN."""
    _require_market_open()
    # buy = net debit, sell = net credit — validate the premium TP/SL bands
    # per direction before any pricing work.
    _validate_premium_mults(
        payload.action == "sell", payload.tp_premium_mult, payload.sl_premium_mult
    )
    _require_tradeable(session, combine, contracts=payload.contracts)
    # WS5: defense-in-depth — clamp the persisted size to the scaling cap.
    contracts = _clamp_contracts_to_cap(session, combine, payload.contracts)
    sym, spot, target_expiry, by_key = _resolve_same_day_quotes(payload.symbol)

    action = payload.action
    side = payload.side
    is_working = payload.order_type in ("limit", "stop", "stop_limit")
    if is_working:
        if payload.limit_price is None or payload.limit_price <= 0:
            raise HTTPException(400, "limit_price must be > 0 for a limit/stop order")
        if payload.order_type == "stop_limit" and (
            payload.stop_price is None or payload.stop_price <= 0
        ):
            raise HTTPException(400, "stop_price must be > 0 for a stop_limit order")
        # Expected fill (placeholder); the monitor overwrites with the real
        # fill premium when the option mark crosses the trigger.
        fill_ref = round(float(payload.limit_price), 4)
    else:
        # SERVER-SIDE market pricing off the LIVE chain quote, through the
        # same slippage machinery as the straddle/multi-leg paths. The
        # client-sent entry_price is display-only: trusting it let a trader
        # select at one premium, wait for the market to move, and book the
        # stale click-time price as instant edge.
        contract_row = by_key.get((round(float(payload.strike), 2), side))
        if contract_row is None:
            raise HTTPException(
                422, f"No {side} at strike {payload.strike:g} for {sym} 0DTE today."
            )
        q = _LegQuote(
            symbol=f"{sym} {side}",
            strike=payload.strike,
            side=side,
            bid=getattr(contract_row, "bid", None),
            ask=getattr(contract_row, "ask", None),
            last=getattr(contract_row, "last", None),
        )
        fill_px = _pick_fill_price(q, action, contracts)
        if fill_px == 0:
            raise HTTPException(
                503, f"{sym} indicative quote unavailable at {side} {payload.strike:g}"
            )
        fill_ref = round(float(fill_px), 4)

    _validate_brackets(spot, payload.stop_loss, payload.take_profit)

    if action == "buy":
        strategy = "long_call" if side == "call" else "long_put"
        notes = f"0DTE long {side} · indicative fill"
    else:
        strategy = "short_call" if side == "call" else "short_put"
        notes = f"0DTE short {side} · indicative credit"
    if is_working:
        if payload.order_type == "stop_limit":
            notes = (
                f"0DTE stop_limit {side} · arms @ {payload.stop_price} → "
                f"limit @ {payload.limit_price}"
            )
        else:
            notes = f"0DTE {payload.order_type} {side} · working @ {payload.limit_price}"

    leg_json = {
        "side": side,
        "action": action,
        "strike": float(payload.strike),
        "expiry": target_expiry.isoformat(),
        "contracts": contracts,
        "entry_price": fill_ref,
    }
    from schemas.journal import TradeLeg
    net = compute_net_debit_credit([TradeLeg(**leg_json)])

    trade = Trade(
        symbol=sym,
        strategy=strategy,
        entry_date=datetime.now(UTC),
        entry_underlying_price=spot,
        net_debit_credit=net,
        status="working" if is_working else "open",
        order_type=payload.order_type,
        limit_price=float(payload.limit_price) if is_working else None,
        stop_price=(
            float(payload.stop_price)
            if is_working and payload.order_type == "stop_limit"
            else None
        ),
        trail_amount=payload.trail_amount,
        trail_pct=payload.trail_pct,
        oco_group=payload.oco_group,
        time_in_force=payload.time_in_force if is_working else "gtc",
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        tp_premium_mult=payload.tp_premium_mult,
        sl_premium_mult=payload.sl_premium_mult,
        is_paper=True,
        notes=notes,
        tier=combine.tier,
        combine_id=combine.id,
    )
    trade.legs = [leg_json]
    trade.tags = ["0dte"]
    trade.mistake_tags = []
    session.add(trade)
    session.commit()
    session.refresh(trade)

    # Copy trading: mirror to follower combines if this is the lead (best-effort).
    mirror_open(session, combine, trade)

    return _trade_to_out(trade)


# ---------------------------------------------------------------------------
# WS5 — Multi-leg strategy builder open endpoint
# ---------------------------------------------------------------------------
#
# Generalizes the straddle open: accept N legs (verticals / iron condors /
# butterflies / any custom multi-leg), validate each is 0DTE-tradeable, price
# each at the indicative MARKET fill (reusing _pick_fill_price), gate via
# _require_tradeable + clamp via _clamp_contracts_to_cap, and persist ONE
# Trade carrying all legs. The existing analytics/chart-overlay path renders
# multi-leg positions unchanged (it already iterates trade.legs).


class MultiLegSpec(BaseModel):
    """One leg of a multi-leg structure. action=buy (long) / sell (short)."""

    side: Literal["call", "put"]
    action: Literal["buy", "sell"]
    strike: float = Field(gt=0)
    # Per-leg ratio multiplier (1 for most legs; e.g. butterfly body = 2). The
    # actual contract count for the leg is contracts × the request's `contracts`.
    ratio: int = Field(gt=0, le=10, default=1)


class OpenMultiLegRequest(BaseModel):
    """Open a multi-leg structure expiring TODAY as a single paper Trade.

    `legs` is 2..6 legs; `contracts` is the base size (each leg gets
    ratio × contracts). `strategy` is an optional label (e.g. "vertical",
    "iron_condor", "butterfly", "custom"); when omitted we infer a generic
    "custom" tag. Always a MARKET fill — like the straddle quick-entry."""

    symbol: str = Field(min_length=1, max_length=16, default="SPY")
    contracts: int = Field(gt=0, le=100, default=1)
    legs: list[MultiLegSpec] = Field(min_length=2, max_length=6)
    strategy: str | None = Field(default=None, max_length=32)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    # Premium-denominated TP/SL. Direction is derived from the PRICED net
    # entry premium (net debit vs net credit), so the bands are validated
    # after the legs are priced — see _validate_premium_mults.
    tp_premium_mult: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Take-profit multiple of |net entry premium|. NET-DEBIT"
            " structure: close when the mark reaches entry × mult (must be"
            " > 1). NET-CREDIT structure the semantics INVERT: the FRACTION"
            " of the collected credit to buy back at (0 < mult < 1; 0.5 ="
            " close at 50% of max profit)."
        ),
    )
    sl_premium_mult: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Stop-loss multiple of |net entry premium|. NET-DEBIT structure:"
            " close when the mark decays to entry × mult (0 < mult < 1)."
            " NET-CREDIT structure: the cut multiple of the credit (must be"
            " > 1; 2.0 = stop when the mark reaches 2× the credit)."
        ),
    )


def _resolve_same_day_quotes(symbol: str) -> tuple[str, float, date, dict]:
    """Resolve the strict-0DTE chain + a {(strike, side): ContractRow} map for
    pricing arbitrary legs. Raises the same 409/503 the leg path does so the
    UI's error handling is consistent. Returns (sym, spot, expiry, by_key)."""
    sym = symbol.upper().strip()
    chain = get_chain_snapshot(sym, with_volume=False)
    if not chain:
        raise HTTPException(503, f"{sym} options chain unavailable")
    today = datetime.now(_ET).date()
    same_day = [c for c in chain if c.expiry == today]
    if not same_day:
        raise HTTPException(
            status_code=409,
            detail=f"0DTE-only: {sym} has no contracts expiring today ({today.isoformat()}).",
        )
    quote = get_quotes([sym]).get(sym)
    if quote is None:
        raise HTTPException(503, f"{sym} quote unavailable")
    spot = float(quote.price)
    by_key = {(round(float(c.strike), 2), c.type): c for c in same_day}
    return sym, spot, today, by_key


@router.post("/open-multi", response_model=TradeOut, status_code=201)
def open_zerodte_multi_leg(
    payload: OpenMultiLegRequest,
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> TradeOut:
    """Open a multi-leg 0DTE structure (vertical / condor / butterfly / custom).

    Each leg is priced at the indicative MARKET fill against today's chain;
    the whole structure becomes one Trade with N legs. Gated by the combine
    rules and the scaling cap (the base `contracts` is what's checked against
    the cap; per-leg ratios scale within the structure). Strict 0DTE +
    session-open, like the straddle/leg paths."""
    _require_market_open()
    # The aggregate scaling cap counts TOTAL contracts across all legs, so a
    # structure consumes base × Σ ratios (e.g. a 4-leg iron condor at base 1 is
    # 4 contracts; a butterfly 1-2-1 is 4). Gate AND clamp on that effective
    # total, then back out the base size.
    sum_ratio = sum(int(spec.ratio) for spec in payload.legs)
    _require_tradeable(session, combine, contracts=payload.contracts * sum_ratio)
    effective = _clamp_contracts_to_cap(session, combine, payload.contracts * sum_ratio)
    base_contracts = max(1, effective // sum_ratio)

    sym, spot, expiry, by_key = _resolve_same_day_quotes(payload.symbol)
    _require_today_expiry(expiry)
    _validate_brackets(spot, payload.stop_loss, payload.take_profit)

    legs_json: list[dict] = []
    for spec in payload.legs:
        leg_qty = spec.ratio * base_contracts
        contract_row = by_key.get((round(spec.strike, 2), spec.side))
        if contract_row is None:
            raise HTTPException(
                422,
                f"No {spec.side} at strike {spec.strike:g} for {sym} 0DTE today.",
            )
        q = _LegQuote(
            symbol=f"{sym} {spec.side}",
            strike=spec.strike,
            side=spec.side,
            bid=getattr(contract_row, "bid", None),
            ask=getattr(contract_row, "ask", None),
            last=getattr(contract_row, "last", None),
        )
        price = _pick_fill_price(q, spec.action, leg_qty)
        if price == 0:
            raise HTTPException(
                503, f"{sym} indicative quote unavailable at {spec.side} {spec.strike:g}"
            )
        legs_json.append(
            {
                "side": spec.side,
                "action": spec.action,
                "strike": float(spec.strike),
                "expiry": expiry.isoformat(),
                "contracts": leg_qty,
                "entry_price": round(price, 4),
            }
        )

    typed_legs = [TradeLeg(**leg) for leg in legs_json]
    net = compute_net_debit_credit(typed_legs)

    # Premium TP/SL direction comes from the PRICED net entry premium:
    # net > 0 → debit (long premium), net < 0 → credit (short premium). A
    # zero-net structure has no premium scale to multiply — reject the mults.
    if payload.tp_premium_mult is not None or payload.sl_premium_mult is not None:
        if net == 0:
            raise HTTPException(
                400,
                "Premium TP/SL requires a non-zero net entry premium — this"
                " structure priced at exactly zero net.",
            )
        _validate_premium_mults(
            net < 0, payload.tp_premium_mult, payload.sl_premium_mult
        )

    strategy = (payload.strategy or "custom").strip().lower() or "custom"
    notes = f"0DTE {strategy.replace('_', ' ')} · {len(legs_json)} legs · indicative fill"

    trade = Trade(
        symbol=sym,
        strategy=strategy,
        entry_date=datetime.now(UTC),
        entry_underlying_price=spot,
        net_debit_credit=net,
        status="open",
        stop_loss=payload.stop_loss,
        take_profit=payload.take_profit,
        tp_premium_mult=payload.tp_premium_mult,
        sl_premium_mult=payload.sl_premium_mult,
        is_paper=True,
        notes=notes,
        tier=combine.tier,
        combine_id=combine.id,
    )
    trade.legs = legs_json
    trade.tags = ["0dte", "multi-leg"]
    trade.mistake_tags = []
    session.add(trade)
    session.commit()
    session.refresh(trade)

    mirror_open(session, combine, trade)
    return _trade_to_out(trade)


def _trade_to_out(trade: Trade) -> TradeOut:
    """Mirror of routers.journal._to_out — kept local so /open and
    /open-leg don't reach across modules for a serializer."""
    return TradeOut(
        id=trade.id,
        symbol=trade.symbol,
        strategy=trade.strategy,
        legs=trade.legs,
        entry_date=trade.entry_date,
        entry_underlying_price=trade.entry_underlying_price,
        net_debit_credit=trade.net_debit_credit,
        status=trade.status,  # type: ignore[arg-type]
        exit_date=trade.exit_date,
        exit_underlying_price=trade.exit_underlying_price,
        realized_pnl=trade.realized_pnl,
        is_paper=trade.is_paper,
        notes=trade.notes,
        tier=trade.tier,
        order_type=trade.order_type,  # type: ignore[arg-type]
        limit_price=trade.limit_price,
        stop_price=trade.stop_price,
        trail_amount=trade.trail_amount,
        trail_pct=trade.trail_pct,
        trail_hwm=trade.trail_hwm,
        oco_group=trade.oco_group,
        stop_loss=trade.stop_loss,
        take_profit=trade.take_profit,
        tp_premium_mult=trade.tp_premium_mult,
        sl_premium_mult=trade.sl_premium_mult,
        close_reason=trade.close_reason,  # type: ignore[arg-type]
        tags=trade.tags,
        mistake_tags=trade.mistake_tags,
        confidence=trade.confidence,
        thesis=trade.thesis,
        planned_exit=trade.planned_exit,
        risk_amount=trade.risk_amount,
        screenshot_url=trade.screenshot_url,
        review_note=trade.review_note,
        r_multiple=trade.r_multiple,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )


# ---------------------------------------------------------------------------
# Pre-trade contract preview — payoff + greeks for the detail panel
# ---------------------------------------------------------------------------


class PreviewRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    kind: Literal["leg", "straddle"] = "leg"
    side: Literal["call", "put"] | None = None
    strike: float = Field(gt=0)
    contracts: int = Field(gt=0, le=100, default=1)


class PreviewGreeks(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float


class ContractPreviewOut(BaseModel):
    symbol: str
    kind: str
    side: str | None
    strike: float
    contracts: int
    spot: float
    iv: float
    expiry: str
    dte_label: str
    entry_price: float                 # per-share net premium (debit)
    cost: float                        # entry_price × 100 × contracts
    open_interest: int | None
    prices: list[float]
    payoff_today: list[float]
    payoff_expiration: list[float]
    breakevens: list[float]
    max_profit: float | None           # null = unbounded
    max_loss: float
    greeks: PreviewGreeks


@router.post("/preview", response_model=ContractPreviewOut)
def preview_contract(payload: PreviewRequest) -> ContractPreviewOut:
    """The long (buy-side) payoff + greeks for a hypothetical contract,
    feeding the trade-ticket's contract-detail panel. Resolves spot / ATM
    IV / T-to-close / per-strike price via the chain table (so it matches
    the chain UI and the indicative-price fallback), then computes the
    payoff diagram from the intraday Black-Scholes engine."""
    sym = payload.symbol.upper().strip()
    # Reuse the chain-table resolver (cached) for spot, IV, T, prices, OI.
    table = get_chain_table(symbol=sym, strikes=40)
    spot = table.spot
    iv = table.iv_used
    t_close = table.t_years_to_close
    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = DEFAULT_RATE_FALLBACK

    row = next((r for r in table.rows if r.strike == payload.strike), None)

    def _leg(side: str) -> dict:
        if row is not None:
            price = row.call_price if side == "call" else row.put_price
            oi = row.call_open_interest if side == "call" else row.put_open_interest
        else:
            # Selected strike outside the window → price it off the engine.
            price = bs_intraday(spot, payload.strike, t_close, rate, iv, side)
            oi = None
        return {
            "side": side,
            "action": "buy",
            "strike": payload.strike,
            "contracts": payload.contracts,
            "entry_price": float(price),
            "_oi": oi,
        }

    if payload.kind == "straddle":
        legs = [_leg("call"), _leg("put")]
        side_out: str | None = None
        oi_out: int | None = None
    else:
        s = payload.side or "call"
        legs = [_leg(s)]
        side_out = s
        oi_out = legs[0]["_oi"]

    preview = compute_contract_preview(
        spot=spot, rate=rate, iv=iv, t_now=t_close, legs=legs
    )

    return ContractPreviewOut(
        symbol=sym,
        kind=payload.kind,
        side=side_out,
        strike=payload.strike,
        contracts=payload.contracts,
        spot=spot,
        iv=iv,
        expiry=table.expiry,
        dte_label="0DTE",
        entry_price=preview.entry_price,
        cost=preview.cost,
        open_interest=oi_out,
        prices=preview.prices,
        payoff_today=preview.payoff_today,
        payoff_expiration=preview.payoff_expiration,
        breakevens=preview.breakevens,
        max_profit=preview.max_profit,
        max_loss=preview.max_loss,
        greeks=PreviewGreeks(**preview.greeks),
    )


# ---------------------------------------------------------------------------
# Flatten / Reverse-all — bulk position management on the active combine
# ---------------------------------------------------------------------------


class FlattenOut(BaseModel):
    """Result of a flatten/reverse. `closed` is the trade ids closed;
    `opened` (reverse only) the new opposite-side trade ids; `realized`
    the total $ booked across the closed positions."""

    closed: list[int]
    opened: list[int] = Field(default_factory=list)
    realized: float


def _open_positions_for_combine(session: Session, combine_id: int) -> list[Trade]:
    return (
        session.execute(
            select(Trade).where(
                Trade.combine_id == combine_id, Trade.status == "open"
            )
        )
        .scalars()
        .all()
    )


def _spot_for_symbol(symbol: str) -> float | None:
    """Live underlying price, or None when the feed is cold/rate-limited."""
    try:
        q = get_quotes([symbol]).get(symbol)
        return float(q.price) if q is not None else None
    except Exception:  # noqa: BLE001
        log.debug("flatten: quote fetch failed for %s", symbol)
        return None


def _close_one(session: Session, trade: Trade, spot: float, now: datetime, reason: str) -> float:
    """Book a single close exactly like the manual CLOSE button + monitor
    (unrealized − exit-side commission), then cascade to follower copies.
    Returns the realized $ booked. Caller owns the commit."""
    # Reuse the monitor's canonical booking helpers so flatten/manual/auto all
    # agree on the realized number.
    from services.order_monitor import _commission_side, _default_unrealized_for

    unrealized = _default_unrealized_for(trade, spot, now)
    realized = round(unrealized - _commission_side(trade), 2)
    trade.status = "closed"
    trade.close_reason = reason
    trade.exit_date = now
    trade.exit_underlying_price = spot
    # ACCUMULATE onto any realized already booked by prior scale-outs — the
    # recompute above covers only the REMAINING contracts, exactly like the
    # monitor's _book_close. A bare assignment here wiped every booked
    # scale-out slice on a flatten/reverse.
    trade.realized_pnl = round((trade.realized_pnl or 0.0) + realized, 2)
    session.flush()
    mirror_close(session, trade)
    return realized


@router.post("/flatten", response_model=FlattenOut)
def flatten_positions(
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> FlattenOut:
    """Close EVERY open position on the active combine at the live mark.

    Uses the same booking path as the manual close + the order monitor
    (unrealized − exit commission) and cascades each close through
    copy_trade.mirror_close. Idempotent: with nothing open it books nothing.
    A position whose underlying quote is cold is left open (can't price it)."""
    now = datetime.now(UTC)
    positions = _open_positions_for_combine(session, combine.id)
    closed: list[int] = []
    total = 0.0
    spot_cache: dict[str, float | None] = {}
    for t in positions:
        if t.symbol not in spot_cache:
            spot_cache[t.symbol] = _spot_for_symbol(t.symbol)
        spot = spot_cache[t.symbol]
        if spot is None:
            continue
        total += _close_one(session, t, spot, now, "manual")
        closed.append(t.id)
    session.commit()
    return FlattenOut(closed=closed, opened=[], realized=round(total, 2))


@router.post("/reverse", response_model=FlattenOut)
def reverse_positions(
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> FlattenOut:
    """Flatten every open position on the active combine AND re-open the
    OPPOSITE side of each at the live mark (buy↔sell flipped, same strikes /
    expiry / size). Refuses when the session is closed (a fresh open can't be
    placed). Reuses the single-close path + mirror cascade for the close half,
    and mirror_open for the new reversed positions."""
    _require_market_open()
    # Reversing re-OPENS fresh positions, so it must clear the SAME risk gate as
    # /open: a FAILED or day-locked combine cannot put on a new book. (Previously
    # /reverse called only _require_market_open, letting a failed/day-locked
    # account re-establish a full opposite-side book and bypass the prop-firm
    # rules every other open path enforces.) Per-position size is clamped to the
    # remaining scaling-cap below.
    _require_tradeable(session, combine)
    now = datetime.now(UTC)
    positions = _open_positions_for_combine(session, combine.id)
    closed: list[int] = []
    opened: list[int] = []
    total = 0.0
    spot_cache: dict[str, float | None] = {}

    for t in positions:
        if t.symbol not in spot_cache:
            spot_cache[t.symbol] = _spot_for_symbol(t.symbol)
        spot = spot_cache[t.symbol]
        if spot is None:
            continue

        # Snapshot the legs BEFORE closing so we can mint the opposite side.
        src_legs = t.legs or []
        total += _close_one(session, t, spot, now, "manual")
        closed.append(t.id)

        if not src_legs:
            continue
        # Flip each leg's action; price the opposite side off the current mark
        # via the same intraday engine the analytics path uses.
        from services.order_monitor import _default_option_mark  # per-leg pricer reuse

        # Clamp the reversed structure to the remaining scaling-cap capacity
        # (the close above frees this position's own size). Scale every leg by
        # the same factor so multi-leg ratios are preserved.
        requested = sum(int(leg.get("contracts", 1) or 1) for leg in src_legs)
        allowed = _clamp_contracts_to_cap(session, combine, requested)
        scale = (allowed / requested) if requested > 0 else 1.0

        rev_legs: list[dict] = []
        for leg in src_legs:
            flipped = "sell" if leg.get("action", "buy") == "buy" else "buy"
            rev_contracts = max(1, int(int(leg.get("contracts", 1) or 1) * scale))
            # Price the flipped leg at the current mark (live chain → model).
            one = dict(leg)
            one["action"] = flipped
            one["contracts"] = rev_contracts
            px = abs(_default_option_mark(_FakeTrade(t.symbol, [one]), spot, now))
            rev_legs.append(
                {
                    "side": leg["side"],
                    "action": flipped,
                    "strike": float(leg["strike"]),
                    "expiry": leg["expiry"],
                    "contracts": rev_contracts,
                    "entry_price": round(float(px), 4),
                }
            )
        net = compute_net_debit_credit([TradeLeg(**leg) for leg in rev_legs])
        rev = Trade(
            symbol=t.symbol,
            strategy=_reverse_strategy(t.strategy),
            entry_date=now,
            entry_underlying_price=spot,
            net_debit_credit=net,
            status="open",
            is_paper=True,
            notes=f"reversed from #{t.id}",
            tier=combine.tier,
            combine_id=combine.id,
        )
        rev.legs = rev_legs
        rev.tags = ["0dte", "reversed"]
        rev.mistake_tags = []
        session.add(rev)
        session.flush()
        mirror_open(session, combine, rev)
        opened.append(rev.id)

    session.commit()
    return FlattenOut(closed=closed, opened=opened, realized=round(total, 2))


class _FakeTrade:
    """Minimal duck-typed stand-in so _default_option_mark (which reads .symbol
    and .legs) can price an ad-hoc single leg without a DB row."""

    def __init__(self, symbol: str, legs: list[dict]) -> None:
        self.symbol = symbol
        self.legs = legs


def _reverse_strategy(strategy: str) -> str:
    """The strategy key for the opposite-side position (long↔short)."""
    flips = {
        "long_call": "short_call",
        "short_call": "long_call",
        "long_put": "short_put",
        "short_put": "long_put",
        "long_straddle": "short_straddle",
        "short_straddle": "long_straddle",
    }
    return flips.get(strategy, strategy)
