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
from models.user import User
from schemas.journal import TradeLeg, TradeOut, compute_net_debit_credit
from services import platform_state
from services.alpaca_client import get_chain_snapshot, get_quotes
from services.auth import get_active_combine
from services.cache import cache
from services.combine_state import CombineSnapshot, combine_snapshot
from services.copy_trade import mirror_close, mirror_open
from services.fills import (
    fill_slippage as _fill_slippage,
    leg_quote as _live_leg_quote,
    live_leg_quotes as _live_leg_quotes,
    pick_fill_price as _pick_fill_price,
)
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
    # PER-CONTRACT implied vol, back-solved from the live quote mid (the
    # smile the flat ATM iv_used can't show). None on BS-fallback sides —
    # they'd only echo iv_used back.
    call_iv: float | None = None
    put_iv: float | None = None


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
    # False when the table shows a LATER expiration than today (multi-expiry
    # browsing): cells are display-only — opening remains strictly 0DTE.
    expiry_is_today: bool = True
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


class ExpirationOut(BaseModel):
    """One listed expiration for the chain browser."""

    expiry: str          # ISO date
    dte: int             # calendar days from today (0 = today)
    is_today: bool


class ExpirationsOut(BaseModel):
    symbol: str
    expirations: list[ExpirationOut]


@router.get("/expirations", response_model=ExpirationsOut)
def get_expirations(symbol: str = "SPY") -> ExpirationsOut:
    """Listed expirations (today or later) for the chain browser's expiry
    selector — audit wave 2's answer to 'there is no expiration selector
    anywhere'. Browsing any expiry is allowed; OPENING remains 0DTE-gated."""
    sym = symbol.upper().strip()
    chain = get_chain_snapshot(sym, with_volume=False)
    if not chain:
        raise HTTPException(503, f"{sym} options chain unavailable")
    today = datetime.now(_ET).date()
    expiries = sorted({c.expiry for c in chain if c.expiry >= today})[:12]
    return ExpirationsOut(
        symbol=sym,
        expirations=[
            ExpirationOut(
                expiry=e.isoformat(), dte=(e - today).days, is_today=(e == today)
            )
            for e in expiries
        ],
    )


class TermPointOut(BaseModel):
    expiry: str
    dte: int
    atm_strike: float
    # ATM implied vol back-solved from the quote mids at THIS expiry's own
    # session close; None when neither ATM side carries a usable quote.
    atm_iv: float | None


class TermStructureOut(BaseModel):
    """ATM implied-vol term structure — the analysis layer a premium seller
    checks before selling today's vol: is the front cheap or rich vs the
    curve? shape: contango (far > near — the normal state), backwardation
    (near > far — event/stress pricing), or flat."""

    symbol: str
    spot: float
    points: list[TermPointOut]
    slope: float | None
    shape: Literal["contango", "backwardation", "flat"] | None


@router.get("/term", response_model=TermStructureOut)
def get_term_structure(symbol: str = "SPY", max_points: int = 8) -> TermStructureOut:
    """ATM IV per listed expiration, one cached chain snapshot + one quote —
    unlocked by the multi-expiry work (wave 2). Each point back-solves the
    ATM call/put mids at that expiry's OWN session close (half-day aware),
    so the front of the curve carries honest intraday time.

    Cached 45s per symbol (review wave 10): the curve is structural and
    slow-moving, and every client polls it at 60s — without the cache each
    tab paid ~16 brentq solves per poll for byte-identical answers."""
    from calculations.intraday_analytics import SECONDS_PER_YEAR
    from services.order_monitor import _session_close_for_date

    sym = symbol.upper().strip()
    cache_key = f"term:{sym}:{max_points}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    chain = get_chain_snapshot(sym, with_volume=False)
    if not chain:
        raise HTTPException(503, f"{sym} options chain unavailable")
    quote = get_quotes([sym]).get(sym)
    if quote is None:
        raise HTTPException(503, f"{sym} quote unavailable")
    spot = float(quote.price)

    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = DEFAULT_RATE_FALLBACK

    now_et = datetime.now(_ET)
    today = now_et.date()
    expiries = sorted({c.expiry for c in chain if c.expiry >= today})
    expiries = expiries[: max(1, min(12, max_points))]

    points: list[TermPointOut] = []
    for e in expiries:
        rows = [c for c in chain if c.expiry == e]
        strikes_ = sorted({c.strike for c in rows})
        if not strikes_:
            continue
        atm = min(strikes_, key=lambda k: abs(k - spot))
        t = max(60.0, (_session_close_for_date(e) - now_et).total_seconds()) / SECONDS_PER_YEAR
        ivs: list[float] = []
        for c in rows:
            if c.strike != atm or c.type not in ("call", "put"):
                continue
            px, _src = _quote_price(c)
            if px is None or px <= 0:
                continue
            iv = iv_intraday(px, spot, atm, t, rate, c.type)
            if iv is not None and iv > 0:
                ivs.append(float(iv))
        points.append(
            TermPointOut(
                expiry=e.isoformat(),
                dte=(e - today).days,
                atm_strike=float(atm),
                atm_iv=round(sum(ivs) / len(ivs), 4) if ivs else None,
            )
        )

    solved = [p for p in points if p.atm_iv is not None]
    slope: float | None = None
    shape: Literal["contango", "backwardation", "flat"] | None = None
    if len(solved) >= 2:
        slope = round(solved[-1].atm_iv - solved[0].atm_iv, 4)  # type: ignore[operator]
        shape = "contango" if slope > 0.005 else "backwardation" if slope < -0.005 else "flat"
    response = TermStructureOut(
        symbol=sym, spot=spot, points=points, slope=slope, shape=shape
    )
    cache.set(cache_key, response, ttl_seconds=45)
    return response


@router.get("/chain/table", response_model=ChainTableOut)
def get_chain_table(
    symbol: str = "SPY",
    strikes: int = 15,
    expiry: str | None = None,
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
    the same cache key, so the expensive bars pass is typically warm.

    The ASSEMBLED response is additionally cached 5s (review wave 10): the
    per-row IV back-solves added in wave 1 are ~2×strikes brentq root-finds
    per request, and every client polls this at 10s — concurrent/adjacent
    polls now share one computation, aligned with the 5s quote cache so
    freshness is unchanged."""
    sym = symbol.upper().strip()
    cache_key = f"chain_table:{sym}:{strikes}:{expiry or 'today'}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    chain = get_chain_snapshot(sym, with_volume=True)
    if not chain:
        raise HTTPException(503, f"{sym} options chain unavailable")
    quote = get_quotes([sym]).get(sym)
    if quote is None:
        raise HTTPException(503, f"{sym} quote unavailable")
    spot = float(quote.price)

    # Expiry resolution (audit wave 2 — multi-expiry BROWSING; opening stays
    # 0DTE-gated in the open paths):
    #   explicit ?expiry=  → that expiry (404 when it isn't listed);
    #   omitted            → today's 0DTE when it exists, else the NEAREST
    #                        upcoming expiry — a no-0DTE day used to 409 and
    #                        dead-terminal the whole chain panel.
    # `expiry_is_today` on the response tells the UI whether cells are
    # tradeable (today) or browse-only (any other expiry).
    today = datetime.now(_ET).date()
    if expiry is not None:
        try:
            target_expiry = date.fromisoformat(expiry)
        except ValueError as exc:
            raise HTTPException(422, f"bad expiry {expiry!r} — use YYYY-MM-DD") from exc
        same_day = [c for c in chain if c.expiry == target_expiry]
        if not same_day:
            raise HTTPException(
                404, f"{sym} has no listed contracts expiring {expiry}."
            )
    else:
        same_day = [c for c in chain if c.expiry == today]
        target_expiry = today
        if not same_day:
            upcoming = sorted({c.expiry for c in chain if c.expiry > today})
            if not upcoming:
                raise HTTPException(
                    status_code=409,
                    detail=f"No 0DTE for {sym} today ({today.isoformat()}).",
                )
            target_expiry = upcoming[0]
            same_day = [c for c in chain if c.expiry == target_expiry]

    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = DEFAULT_RATE_FALLBACK
    # Time-to-expiry for the TARGET expiry's session close (half-day aware) —
    # today's close for 0DTE (the legacy path), the expiry's own close when
    # browsing a later expiration.
    if target_expiry == today:
        t_close = _t_years_to_close()
    else:
        from calculations.intraday_analytics import SECONDS_PER_YEAR
        from services.order_monitor import _session_close_for_date

        secs = max(
            60.0,
            (_session_close_for_date(target_expiry) - datetime.now(_ET)).total_seconds(),
        )
        t_close = secs / SECONDS_PER_YEAR

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

        # Per-contract IV from the quote mid (smile/skew visibility). Only
        # for quote-sourced sides — a BS-priced side would just echo iv_used.
        call_iv = (
            iv_intraday(float(call_px), spot, k, t_close, rate, "call")
            if call_source == "quote"
            else None
        )
        put_iv = (
            iv_intraday(float(put_px), spot, k, t_close, rate, "put")
            if put_source == "quote"
            else None
        )

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
                call_iv=round(call_iv, 4) if call_iv is not None else None,
                put_iv=round(put_iv, 4) if put_iv is not None else None,
            )
        )

    response = ChainTableOut(
        underlying=sym,
        spot=spot,
        expiry=target_expiry.isoformat(),
        atm_strike=atm,
        iv_used=iv_used,
        iv_source=iv_source,
        rows=rows,
        t_years_to_close=t_close,
        session_close_iso=_session_close_et().isoformat(),
        expiry_is_today=(target_expiry == today),
        as_of=_chain_as_of(quote, same_day),
    )
    cache.set(cache_key, response, ttl_seconds=5)
    return response


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


# The deterministic spread-crossing fill machinery (`_fill_slippage` /
# `_pick_fill_price`) moved VERBATIM to services.fills so the order monitor
# and journal close paths charge the same friction the user-facing market
# opens do (audit C4). Imported above under the historical names — this
# module's call sites and its tests are unchanged.


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


def _require_symbol_tradeable(session: Session, symbol: str) -> None:
    """Universe enforcement on the OPEN path (risk controls, B5).

    When settings.enforce_tradeable_universe is on, a symbol outside
    settings.zero_dte_universe — or on the operator's DB-backed ban list
    (platform_state) — cannot be OPENED. Closes are deliberately never
    symbol-gated: an existing position in a just-banned symbol must stay
    exitable. No market-data dependency (a set lookup + one DB get), so the
    gate works exactly when the data feed is the thing that broke."""
    if not settings.enforce_tradeable_universe:
        return
    sym = symbol.upper().strip()
    universe = {s.upper() for s in settings.zero_dte_universe}
    if sym not in universe or sym in platform_state.get_banned_symbols(session):
        raise HTTPException(
            status_code=422,
            detail=f"symbol_not_tradeable: {sym} is not in the tradeable universe",
        )


def _require_quote_quality(
    sym: str, labeled_quotes: list[tuple[str, object, str]]
) -> None:
    """Refuse an OPEN against an unusable option market (risk controls, B5).

    The gate is ACTION-AWARE, because the risk differs by side:

      * SELL legs (writing premium) get the FULL check — a genuine two-sided
        NBBO, mid ≥ settings.min_option_mid, and relative spread ≤
        settings.max_option_spread_ratio. Selling into a one-sided / fantasy
        market is the exploit the gate exists to stop: the fill machinery
        would synthesize a price for a contract nobody actually bids, letting
        a trader "collect" premium the firm could never hedge.

      * BUY legs (paying premium) only need a real ASK to lift. A protective
        long wing of a defined-risk structure (credit spread, iron condor) is
        NORMALLY a cheap, wide, zero-bid far-OTM contract — legitimately so.
        Applying the sell-side checks to it (as the first cut did) blocked
        every defined-risk structure while leaving the NAKED short body
        openable — inverting the gate's own purpose. Paying up for a wide buy
        is not an exploit, so a buy leg passes on ask > 0 alone.

    OPENS ONLY — closes and liquidations must never be blocked by quote
    quality (an exit is always allowed, whatever the market looks like).
    Working-order placements are not gated either: they fill later through
    the monitor at the user's own limit, not against this quote. Fill math
    is untouched — this is a yes/no door, not a pricing change."""
    for label, q, action in labeled_quotes:
        raw_bid = getattr(q, "bid", None)
        raw_ask = getattr(q, "ask", None)
        bid = float(raw_bid) if raw_bid and raw_bid > 0 else 0.0
        ask = float(raw_ask) if raw_ask and raw_ask > 0 else 0.0
        if action == "buy":
            # A buy fills at the ask — it only needs a real offer to cross to.
            if ask <= 0.0:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"quote_quality: {sym} {label} leg has no offer to buy "
                        f"(ask ${ask:.2f})"
                    ),
                )
            continue
        # SELL leg — the full anti-fantasy-market check.
        if bid <= 0.0 or ask <= 0.0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"quote_quality: {sym} {label} leg has an unusable market "
                    f"(one-sided quote — bid ${bid:.2f} / ask ${ask:.2f})"
                ),
            )
        mid = (bid + ask) / 2.0  # > 0: both sides positive above (no div-by-zero)
        if mid < settings.min_option_mid:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"quote_quality: {sym} {label} leg has an unusable market "
                    f"(mid ${mid:.2f} is below the ${settings.min_option_mid:.2f} minimum)"
                ),
            )
        spread_ratio = (ask - bid) / mid
        if spread_ratio > settings.max_option_spread_ratio:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"quote_quality: {sym} {label} leg has an unusable market "
                    f"(mid ${mid:.2f}, spread {spread_ratio * 100.0:.0f}%)"
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
                # Only execution fills bear combine risk / consume the cap;
                # manual journal rows are record-keeping.
                Trade.origin == "execution",
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
    session: Session,
    combine: Combine,
    requested: int,
    snap: "CombineSnapshot | None" = None,
) -> int:
    """Defense-in-depth size clamp. `_require_tradeable` already REJECTS an
    over-cap request with a 422, but this clamps the per-order size to the
    remaining scaling-plan capacity as a belt-and-suspenders guard so a leg
    can never be persisted above the cap even if the gate is bypassed or the
    snapshot shifts under us. Returns the size to actually use (>=1).

    The cap is per-COMBINE aggregate: remaining = max_contracts − already-open.
    With nothing open and a cap of N this is a no-op (returns `requested`).
    Pass the snapshot from _require_tradeable when available — recomputing it
    per gate tripled the heaviest account computation on every open."""
    snap = snap or combine_snapshot(session, combine)
    open_now = _open_contracts_for_combine(session, combine.id)
    remaining = max(0, snap.max_contracts - open_now)
    # Never clamp below 1 — a 0-contract order is meaningless; the reject path
    # in _require_tradeable owns the "no room at all" case (open_now >= cap).
    return max(1, min(int(requested), remaining)) if remaining > 0 else int(requested)
# ── end WS5 ─────────────────────────────────────────────────────────────────


def _book_margin_used(session: Session, combine_id: int, spot_hint: dict[str, float]) -> float:
    """$ requirement already committed by the combine's OPEN + WORKING
    execution book (working orders reserved margin at placement). Spot per
    symbol comes from `spot_hint` (the caller's live quote), then a live
    fetch, then the trade's own entry underlying — margin can never be
    bypassed by a cold feed, only priced slightly stale."""
    from calculations.margin import book_requirement

    rows = (
        session.execute(
            select(Trade).where(
                Trade.combine_id == combine_id,
                Trade.status.in_(("open", "working")),
                Trade.origin == "execution",
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return 0.0
    spot_cache: dict[str, float] = dict(spot_hint)
    # ONE batched quote call for every symbol the hint didn't cover — the
    # house convention (StockSnapshotRequest batches server-side); the old
    # per-symbol loop paid a round-trip apiece on the 5s header poll.
    missing = sorted({t.symbol for t in rows} - set(spot_cache))
    if missing:
        try:
            for sym, q in (get_quotes(missing) or {}).items():
                if q is not None and float(q.price) > 0:
                    spot_cache[sym] = float(q.price)
        except Exception:  # noqa: BLE001 — cold feed → entry-price fallback below
            log.debug("book margin: batched quote fetch failed for %s", missing)
    structures: list[tuple[list[dict], float]] = []
    for t in rows:
        spot = spot_cache.get(t.symbol)
        structures.append(
            (t.legs, spot if spot is not None else float(t.entry_underlying_price))
        )
    return book_requirement(
        structures,
        naked_pct=settings.margin_naked_pct,
        naked_min_pct=settings.margin_naked_min_pct,
    )


def _require_buying_power(
    session: Session,
    combine: Combine,
    symbol: str,
    new_legs: list[dict],
    spot: float,
    snap: "CombineSnapshot | None" = None,
    release_legs: list[dict] | None = None,
) -> None:
    """MARGIN GATE — the capital constraint the audit flagged as absent
    (order cost was never checked and naked shorts were free). The new
    structure's requirement (max loss for defined-risk, Reg-T-style for
    naked sides — calculations/margin.py) plus what the existing open +
    working book already commits must fit inside the realized balance.

    Balance is the REALIZED balance (open URPL not counted — the live
    MLL/DLL gates in _require_tradeable own unrealized exposure). Closes
    never come through here, so a trader can always exit. Config-off →
    legacy behavior.

    `snap`: pass the snapshot _require_tradeable already computed (review
    wave 10: three snapshots per open request). `release_legs`: a structure
    the caller is about to close as part of the same action (the ROLL swap)
    — its requirement is credited back before the new one is tested, so a
    refused roll can never be stricter than the equivalent fresh open."""
    if not settings.margin_enforcement_enabled:
        return
    from calculations.margin import structure_requirement

    _mkw = dict(
        naked_pct=settings.margin_naked_pct,
        naked_min_pct=settings.margin_naked_min_pct,
    )
    new_req = structure_requirement(new_legs, spot, **_mkw)
    if new_req <= 0:
        return
    snap = snap or combine_snapshot(session, combine)
    used = _book_margin_used(session, combine.id, {symbol: float(spot)})
    if release_legs:
        used = max(0.0, used - structure_requirement(release_legs, spot, **_mkw))
    available = snap.balance - used
    if new_req > available:
        raise HTTPException(
            422,
            f"insufficient buying power: this structure requires "
            f"${new_req:,.0f} but only ${max(0.0, available):,.0f} is "
            f"available (balance ${snap.balance:,.0f} − ${used:,.0f} "
            "committed to open/working positions). Reduce size or use a "
            "defined-risk structure.",
        )


def _live_combine_urpl(session: Session, combine: Combine) -> float:
    """Live mark-to-market URPL of the combine's OPEN positions. Best-effort and
    fully resilient: any pricing failure (cold feed / circuit open / no creds)
    contributes 0, so the order-time gate degrades to the realized-only check
    rather than blocking wrongly. The order monitor + auto-liquidation (config-driven cadence, default 5s) remain the
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
    session: Session,
    combine: Combine,
    contracts: int | None = None,
    symbol: str | None = None,
) -> "CombineSnapshot":
    """Enforce the combine's standing rules on the OPEN path — the rule
    actually binds server-side, not just via the trade-ticket soft-gate.
    Blocks a FAILED eval (MLL floor breached; must be reset) and a DAY
    LOCK (today's DLL hit; lifts at the 5pm-PT settlement). A PASSED /
    funded account is NOT blocked — it keeps trading to accrue payout.
    When `contracts` is given, also enforces the SCALING PLAN: the
    requested size can't exceed the max allowed at the current built
    equity (fixed intraday; re-evaluates at the 5pm-PT settlement).
    Computing the snapshot here also persists any pending settlement.

    Every OPEN path comes through here — straddle, single-leg, multi-leg
    and /reverse re-opens (copy-trade mirrors transitively: mirror_open
    only runs after the lead's open passes this gate, and monitor-side
    fills of mirrored working orders are gated in order_monitor). Closes
    never call it, so the platform-mode checks can hard-refuse."""
    # ── Operator kill switch + account state (risk controls, B5) ────────────
    # Cheapest first: two DB gets (user + platform mode) and a set lookup, no
    # market data, before any snapshot/settlement math below.
    user = session.get(User, combine.user_id)
    if user is not None and user.suspended_at is not None:
        raise HTTPException(
            status_code=403,
            detail="account_suspended: your account is suspended — contact support",
        )
    mode = platform_state.get_trading_mode(session)
    if mode == "halted":
        raise HTTPException(
            status_code=503,
            detail="trading_halted: trading is temporarily halted",
        )
    if mode == "close_only":
        raise HTTPException(
            status_code=409,
            detail="close_only: only closing orders are being accepted right now",
        )
    if symbol is not None:
        _require_symbol_tradeable(session, symbol)

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
    # MLL floor or has exhausted today's DLL budget. The next monitor pass would
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
    # Hand the snapshot back so the rest of the open path (size clamp, margin
    # gate) reuses it instead of recomputing — combine_snapshot is the
    # heaviest account computation in the codebase, and the review found
    # THREE of them per open request (wave 10 efficiency cluster).
    return snap


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
    snap = _require_tradeable(
        session, combine, contracts=payload.contracts * 2, symbol=payload.symbol
    )
    allowed_total = _clamp_contracts_to_cap(
        session, combine, payload.contracts * 2, snap=snap
    )
    contracts = max(1, allowed_total // 2)
    sym, spot, expiry, atm, call_q, put_q = _resolve_atm_chain(payload.symbol)
    _require_today_expiry(expiry)
    # Quote-quality gate — an immediate market fill needs a usable two-sided
    # NBBO on BOTH legs (opens only; closes are never quote-gated).
    _require_quote_quality(
        sym,
        [
            (f"call {atm:g}", call_q, payload.action),
            (f"put {atm:g}", put_q, payload.action),
        ],
    )

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

    # MARGIN GATE — priced legs in hand, check the capital requirement.
    _require_buying_power(session, combine, sym, legs_json, spot, snap=snap)

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
    snap = _require_tradeable(
        session, combine, contracts=payload.contracts, symbol=payload.symbol
    )
    # WS5: defense-in-depth — clamp the persisted size to the scaling cap.
    contracts = _clamp_contracts_to_cap(session, combine, payload.contracts, snap=snap)
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
        # Quote-quality gate — an immediate market fill needs a usable
        # two-sided NBBO (opens only; working orders fill later through the
        # monitor at the user's own limit, and closes are never quote-gated).
        _require_quote_quality(
            sym, [(f"{side} {payload.strike:g}", contract_row, payload.action)]
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

    # MARGIN GATE — applies to immediate fills AND working orders (a resting
    # order reserves its requirement at placement, like the contract cap).
    _require_buying_power(session, combine, sym, [leg_json], spot, snap=snap)

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
    # "market" (default) fills every leg immediately at the indicative crossed
    # quote. "limit" places a WORKING net-premium order: the monitor prices the
    # structure's live net each pass and fills when it satisfies limit_price.
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = Field(
        default=None,
        description=(
            "NET premium limit per 1x structure (legs at their stated ratios),"
            " $/share — required for order_type='limit', ignored for market."
            " SIGN CONVENTION: debit positive / credit negative. A positive"
            " limit fills when the structure's live net DEBIT ≤ limit (pay at"
            " most this much); a negative limit fills when the live net CREDIT"
            " ≥ |limit| (collect at least this much). Must be non-zero."
        ),
    )
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

    order_type="market" (default): each leg is priced at the indicative MARKET
    fill against today's chain; the whole structure becomes one Trade with N
    legs. order_type="limit": a WORKING net-premium order (status='working',
    no fill) — the monitor prices the structure's live net each pass and fills
    when the net debit ≤ limit_price (debit structures, limit > 0) or the net
    credit ≥ |limit_price| (credit structures, limit < 0). Working orders
    follow single-leg semantics: cancel via /cancel, expired contracts are
    purged, and their contracts count against the scaling cap. Gated by the
    combine rules and the scaling cap (the base `contracts` is what's checked
    against the cap; per-leg ratios scale within the structure). Strict 0DTE +
    session-open, like the straddle/leg paths."""
    _require_market_open()
    is_working = payload.order_type == "limit"
    if is_working and (payload.limit_price is None or payload.limit_price == 0):
        raise HTTPException(
            400,
            "limit_price (net premium per 1x structure; debit positive, credit"
            " negative, non-zero) is required for a limit order",
        )
    # The aggregate scaling cap counts TOTAL contracts across all legs, so a
    # structure consumes base × Σ ratios (e.g. a 4-leg iron condor at base 1 is
    # 4 contracts; a butterfly 1-2-1 is 4). Gate AND clamp on that effective
    # total, then back out the base size.
    sum_ratio = sum(int(spec.ratio) for spec in payload.legs)
    snap = _require_tradeable(
        session, combine, contracts=payload.contracts * sum_ratio, symbol=payload.symbol
    )
    effective = _clamp_contracts_to_cap(
        session, combine, payload.contracts * sum_ratio, snap=snap
    )
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
        if is_working:
            # A resting order doesn't fill NOW — the leg's entry_price is a
            # display placeholder at the current mid (0 when unquoted); the
            # monitor overwrites it with the real crossed fill.
            mid, _src = _quote_price(contract_row)
            price = float(mid) if mid is not None and mid > 0 else 0.0
        else:
            # Quote-quality gate — every leg of an immediate market fill needs
            # a usable two-sided NBBO (opens only). Raising here is safe: the
            # Trade row is only persisted after the whole loop.
            _require_quote_quality(
                sym, [(f"{spec.side} {spec.strike:g}", contract_row, spec.action)]
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

    # Premium TP/SL direction comes from the PRICED net entry premium (or the
    # SIGNED limit for a working order — the placeholder net may be 0 when the
    # chain has gaps): net/limit > 0 → debit (long premium), < 0 → credit
    # (short premium). A zero-net market structure has no premium scale to
    # multiply — reject the mults.
    if payload.tp_premium_mult is not None or payload.sl_premium_mult is not None:
        if is_working:
            _validate_premium_mults(
                payload.limit_price < 0, payload.tp_premium_mult, payload.sl_premium_mult
            )
        else:
            if net == 0:
                raise HTTPException(
                    400,
                    "Premium TP/SL requires a non-zero net entry premium — this"
                    " structure priced at exactly zero net.",
                )
            _validate_premium_mults(
                net < 0, payload.tp_premium_mult, payload.sl_premium_mult
            )

    # MARGIN GATE — the multi-leg structure's requirement (defined-risk max
    # loss, or Reg-T-style when a side is net short) vs remaining buying power.
    _require_buying_power(session, combine, sym, legs_json, spot, snap=snap)

    strategy = (payload.strategy or "custom").strip().lower() or "custom"
    if is_working:
        notes = (
            f"0DTE {strategy.replace('_', ' ')} · {len(legs_json)} legs · "
            f"working @ net {payload.limit_price:g}"
        )
    else:
        notes = f"0DTE {strategy.replace('_', ' ')} · {len(legs_json)} legs · indicative fill"

    trade = Trade(
        symbol=sym,
        strategy=strategy,
        entry_date=datetime.now(UTC),
        entry_underlying_price=spot,
        net_debit_credit=net,
        status="working" if is_working else "open",
        order_type=payload.order_type,
        limit_price=float(payload.limit_price) if is_working else None,
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
        close_limit_price=trade.close_limit_price,
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
    # Pre-trade TIME SCRUBBER (audit wave 6): what-if minutes-to-close for
    # the T+0 curve and greeks — "what does this position look like at
    # 3:30pm?". Entry PRICING always uses the real now (you buy at the
    # market, then time passes); clamped to [1, actual minutes to close].
    # None = now (legacy behavior).
    minutes_to_close: float | None = Field(default=None, gt=0)


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
    max_loss: float | None             # null = unbounded (multi-leg net short calls)
    greeks: PreviewGreeks
    # Closed-form model probabilities (risk-neutral lognormal, ATM IV):
    # prob_itm — the contract finishes ITM at expiry (null for a straddle);
    # pop_long / pop_short — probability of profit at expiry for each
    # direction of the shown structure (short = 1 − long).
    prob_itm: float | None = None
    pop_long: float | None = None
    pop_short: float | None = None
    # Buying-power requirement (calculations/margin.py) so the cost of
    # capital is visible BEFORE firing: long = the debit (max loss); short =
    # the Reg-T-style naked/defined-risk requirement — usually many times
    # the premium collected. /preview-multi fills bp_requirement_long with
    # the as-submitted structure's requirement (short is null there).
    bp_requirement_long: float | None = None
    bp_requirement_short: float | None = None


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

    # Time scrubber: the T+0 curve/greeks evaluate at the what-if clock,
    # clamped so a scrub can never ADD time (max = the real time to close)
    # or hit T=0 exactly (60s floor keeps BS finite). Entry pricing above
    # already used the real now.
    t_view = t_close
    if payload.minutes_to_close is not None:
        from calculations.intraday_analytics import SECONDS_PER_YEAR

        t_view = min(
            t_close, max(60.0, payload.minutes_to_close * 60.0) / SECONDS_PER_YEAR
        )

    preview = compute_contract_preview(
        spot=spot, rate=rate, iv=iv, t_now=t_view, legs=legs
    )

    # Closed-form probabilities at expiry (risk-neutral, ATM IV) — prob-ITM
    # off the strike, POP off the structure's breakevens. The short side is
    # the exact complement of the long side at expiry.
    from calculations.probability import pop_long as _pop_long
    from calculations.probability import prob_itm as _prob_itm

    itm = (
        _prob_itm(spot, payload.strike, t_close, rate, iv, side_out)
        if side_out in ("call", "put")
        else None
    )
    pop_l = _pop_long(spot, preview.breakevens, t_close, rate, iv, side_out)
    pop_s = None if pop_l is None else max(0.0, min(1.0, 1.0 - pop_l))

    # Buying-power requirement per direction: the preview's legs are LONG
    # (all buys); the short side is the same structure with actions flipped.
    from calculations.margin import structure_requirement

    _mkw = dict(
        naked_pct=settings.margin_naked_pct,
        naked_min_pct=settings.margin_naked_min_pct,
    )
    clean_legs = [{k: v for k, v in leg.items() if k != "_oi"} for leg in legs]
    bp_long = structure_requirement(clean_legs, spot, **_mkw)
    bp_short = structure_requirement(
        [{**leg, "action": "sell"} for leg in clean_legs], spot, **_mkw
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
        dte_label=(
            "0DTE"
            if table.expiry_is_today
            else f"{(date.fromisoformat(table.expiry) - datetime.now(_ET).date()).days}DTE"
        ),
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
        prob_itm=None if itm is None else round(itm, 4),
        pop_long=None if pop_l is None else round(pop_l, 4),
        pop_short=None if pop_s is None else round(pop_s, 4),
        bp_requirement_long=bp_long,
        bp_requirement_short=bp_short,
    )


class PreviewMultiRequest(BaseModel):
    """Pre-trade preview for an arbitrary 2–6 leg structure AS SUBMITTED
    (buys and sells at their stated ratios) — the builder's risk graph."""

    symbol: str = Field(min_length=1, max_length=16, default="SPY")
    contracts: int = Field(gt=0, le=100, default=1)
    legs: list[MultiLegSpec] = Field(min_length=2, max_length=6)


@router.post("/preview-multi", response_model=ContractPreviewOut)
def preview_multi(payload: PreviewMultiRequest) -> ContractPreviewOut:
    """Payoff / greeks / breakevens / POP for a hypothetical multi-leg
    structure, priced off the same chain table as the ladder. Unlike
    /preview (long-only single/straddle), this evaluates the structure AS
    SUBMITTED — short legs negative — so credit spreads, condors and ratio
    structures preview honestly. Max profit/loss are taken at the payoff's
    critical points (S→0, each strike, and past the top strike), with the
    unbounded sides flagged via net call exposure."""
    from calculations.probability import pop_from_curve

    sym = payload.symbol.upper().strip()
    table = get_chain_table(symbol=sym, strikes=40)
    spot = table.spot
    iv = table.iv_used
    t_close = table.t_years_to_close
    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = DEFAULT_RATE_FALLBACK

    def _indicative(side: str, strike: float) -> float:
        row = next((r for r in table.rows if r.strike == strike), None)
        if row is not None:
            px = row.call_price if side == "call" else row.put_price
            if px and px > 0:
                return float(px)
        return float(bs_intraday(spot, strike, t_close, rate, iv, side))

    legs = [
        {
            "side": spec.side,
            "action": spec.action,
            "strike": spec.strike,
            "contracts": spec.ratio * payload.contracts,
            "entry_price": _indicative(spec.side, spec.strike),
        }
        for spec in payload.legs
    ]
    preview = compute_contract_preview(
        spot=spot, rate=rate, iv=iv, t_now=t_close, legs=legs
    )

    # Expiry payoff — the SHARED analytic evaluator (calculations/margin),
    # the same function the margin gate and exact_breakevens root (review
    # cleanup: this endpoint carried its own byte-identical copy).
    from calculations.margin import payoff_at_expiry

    def _sign(leg: dict) -> int:
        return 1 if leg["action"] == "buy" else -1

    def _payoff_at(s: float) -> float:
        return payoff_at_expiry(legs, s)

    # Bounded extremes live at the payoff's critical points: S→0, each
    # strike, and anywhere past the top strike (the tail is flat unless net
    # call exposure makes it unbounded).
    net_calls = sum(_sign(l) * l["contracts"] for l in legs if l["side"] == "call")
    strikes = sorted({float(l["strike"]) for l in legs})
    critical = [0.0, *strikes, strikes[-1] * 1.5 + 1.0]
    values = [_payoff_at(s) for s in critical]
    max_profit = None if net_calls > 0 else round(max(values), 2)
    max_loss = None if net_calls < 0 else round(min(values), 2)

    # POP roots the payoff ANALYTICALLY (review wave 9, finding 9): the
    # ±25% preview grid misses tail crossings, which hard-printed 1.0/0.0
    # for structures whose breakevens sit outside it.
    from calculations.margin import exact_breakevens

    pop = pop_from_curve(spot, exact_breakevens(legs), t_close, rate, iv, _payoff_at)

    # Buying-power requirement for the structure AS SUBMITTED — the number
    # the margin gate will hold against the balance at open.
    from calculations.margin import structure_requirement

    bp_req = structure_requirement(
        legs,
        spot,
        naked_pct=settings.margin_naked_pct,
        naked_min_pct=settings.margin_naked_min_pct,
    )

    return ContractPreviewOut(
        symbol=sym,
        kind="multi",
        side=None,
        strike=strikes[0],
        contracts=payload.contracts,
        spot=spot,
        iv=iv,
        expiry=table.expiry,
        dte_label=(
            "0DTE"
            if table.expiry_is_today
            else f"{(date.fromisoformat(table.expiry) - datetime.now(_ET).date()).days}DTE"
        ),
        entry_price=preview.entry_price,
        cost=preview.cost,
        open_interest=None,
        prices=preview.prices,
        payoff_today=preview.payoff_today,
        payoff_expiration=preview.payoff_expiration,
        breakevens=preview.breakevens,
        max_profit=max_profit,
        max_loss=max_loss,
        greeks=PreviewGreeks(**preview.greeks),
        prob_itm=None,
        pop_long=round(pop, 4),
        pop_short=round(max(0.0, min(1.0, 1.0 - pop)), 4),
        bp_requirement_long=bp_req,
        bp_requirement_short=None,
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


def _close_one(
    session: Session, trade: Trade, spot: float, now: datetime, reason: str
) -> float | None:
    """Book a single close exactly like the manual CLOSE button + monitor
    (unrealized − exit-side commission − spread-crossing exit friction), then
    cascade to follower copies. Routes through the monitor's `_book_close` so
    flatten/manual/auto all agree on the realized number AND share its
    conditional status claim — returns None when the close lost the race (a
    bracket/liquidation already booked it; never double-book). Otherwise
    returns the realized $ booked for THIS close. Caller owns the commit."""
    from services.order_monitor import _book_close, _default_unrealized_for

    prior = trade.realized_pnl or 0.0
    booked = _book_close(
        session, trade, spot, now,
        lambda t, s: _default_unrealized_for(t, s, now), reason,
    )
    if not booked:
        return None
    session.flush()
    # Cascade the just-booked slice (delta) to followers so a scaled-out lead's
    # earlier slices aren't re-booked.
    mirror_close(session, trade, final_slice_pnl=round((trade.realized_pnl or 0.0) - prior, 2))
    return round((trade.realized_pnl or 0.0) - prior, 2)


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
        realized = _close_one(session, t, spot, now, "manual")
        if realized is None:
            continue  # already closed concurrently (bracket/liquidation)
        total += realized
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
    snap = _require_tradeable(session, combine)
    now = datetime.now(UTC)
    positions = _open_positions_for_combine(session, combine.id)
    # Reversing re-OPENS the opposite side of every held position, so each
    # held symbol must still be open-eligible (universe + ban list). Checked
    # UP FRONT — before any close books — so a banned symbol refuses the whole
    # action atomically instead of flattening half the book. Plain closes are
    # never symbol-gated: /flatten remains the exit for a banned symbol.
    for held_symbol in sorted({t.symbol for t in positions}):
        _require_symbol_tradeable(session, held_symbol)
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
        realized = _close_one(session, t, spot, now, "manual")
        if realized is None:
            continue  # already closed concurrently — nothing to reverse
        total += realized
        closed.append(t.id)

        if not src_legs:
            continue
        # Flip each leg's action; price the opposite side by CROSSING THE
        # SPREAD on the live quote where one exists (a reverse re-open is a
        # market fill like any other open), falling back to the model mid via
        # the same intraday engine the analytics path uses.
        from services.order_monitor import _default_option_mark  # per-leg pricer reuse

        live_qs = _live_leg_quotes(t.symbol, src_legs)

        # Clamp the reversed structure to the remaining scaling-cap capacity
        # (the close above frees this position's own size). Scale every leg by
        # the same factor so multi-leg ratios are preserved.
        requested = sum(int(leg.get("contracts", 1) or 1) for leg in src_legs)
        allowed = _clamp_contracts_to_cap(session, combine, requested, snap=snap)
        scale = (allowed / requested) if requested > 0 else 1.0

        rev_legs: list[dict] = []
        for leg in src_legs:
            flipped = "sell" if leg.get("action", "buy") == "buy" else "buy"
            rev_contracts = max(1, int(int(leg.get("contracts", 1) or 1) * scale))
            # Price the flipped leg at the crossed live quote → current mark.
            one = dict(leg)
            one["action"] = flipped
            one["contracts"] = rev_contracts
            q = _live_leg_quote(live_qs, leg)
            px = _pick_fill_price(q, flipped, rev_contracts) if q is not None else 0.0
            if px <= 0:
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
        # MARGIN GATE — flipping a book can transform its requirement (a long
        # straddle reverses into a naked short straddle). A reversed structure
        # that doesn't fit the remaining buying power is SKIPPED (that position
        # ends flat, never over-levered); the close above already booked.
        try:
            _require_buying_power(
                session, combine, t.symbol, rev_legs, spot, snap=snap
            )
        except HTTPException:
            continue
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


class RollRequest(BaseModel):
    """Roll an OPEN position to new strikes as ONE action — the core
    management move on every real options platform (Tastytrade's one-click
    roll, ToS right-click → Roll). 0DTE product → same-expiry STRIKE rolls:
    every leg shifts by the same amount, preserving the structure's widths.

    Exactly one of:
      strike_shift — signed points to move every leg ("roll up 5");
      to_atm=True  — shift so the anchor leg (the strike nearest the entry
                     underlying; a straddle's shared strike) lands on the
                     current ATM ("re-center").
    """

    trade_id: int
    strike_shift: float | None = None
    to_atm: bool = False


class RollOut(BaseModel):
    closed: int
    opened: int
    realized: float           # $ booked closing the old position
    net_debit_credit: float   # the NEW position's net entry ($, signed)


@router.post("/roll", response_model=RollOut)
def roll_position(
    payload: RollRequest,
    combine: Combine = Depends(get_active_combine),
    session: Session = Depends(get_session),
) -> RollOut:
    """Close the position at the live mark and reopen the same structure
    (same sides/actions/sizes/expiry) at shifted strikes, atomically enough
    that a refused roll leaves the position UNTOUCHED: every gate — market
    open, tradeable, target strikes listed, margin after the swap — is
    checked BEFORE the close books. Underlying-price brackets and any
    resting close-limit are dropped (they priced the old strikes); premium
    TP/SL multiples and trailing stops carry over (they re-anchor to the new
    entry premium automatically)."""
    _require_market_open()
    snap = _require_tradeable(session, combine)

    trade = session.get(Trade, payload.trade_id)
    if trade is None or trade.combine_id != combine.id:
        raise HTTPException(404, "no such position on the active combine")
    if trade.status != "open":
        raise HTTPException(409, "only an open position can be rolled")
    if (payload.strike_shift is None) == (not payload.to_atm):
        raise HTTPException(422, "specify exactly one of strike_shift / to_atm")
    _require_symbol_tradeable(session, trade.symbol)

    src_legs = trade.legs or []
    if not src_legs:
        raise HTTPException(422, "position has no usable legs")

    spot = _spot_for_symbol(trade.symbol)
    if spot is None:
        raise HTTPException(503, f"{trade.symbol} quote unavailable — can't roll")

    # Today's listed strikes for the target validation (+ ATM for re-center).
    chain = get_chain_snapshot(trade.symbol, with_volume=False)
    today = datetime.now(_ET).date()
    listed = sorted({c.strike for c in chain if c.expiry == today})
    if not listed:
        raise HTTPException(409, f"No 0DTE for {trade.symbol} today — nothing to roll into.")

    if payload.to_atm:
        atm = min(listed, key=lambda k: abs(k - spot))
        anchor = min(
            (float(leg["strike"]) for leg in src_legs),
            key=lambda k: abs(k - float(trade.entry_underlying_price)),
        )
        shift = atm - anchor
        if shift == 0:
            raise HTTPException(409, "position is already centered on the ATM strike")
    else:
        shift = float(payload.strike_shift or 0.0)
        if shift == 0:
            raise HTTPException(422, "strike_shift must be non-zero")

    new_strikes = [float(leg["strike"]) + shift for leg in src_legs]
    unlisted = [k for k in new_strikes if k not in listed]
    if unlisted:
        raise HTTPException(
            422,
            f"target strike(s) {', '.join(f'{k:g}' for k in unlisted)} are not "
            f"listed for {trade.symbol} today — adjust the shift to the strike grid",
        )

    # Price the new legs at the crossed live quote (a roll's open half is a
    # market fill like any other open), model-mid fallback per leg.
    from services.order_monitor import _default_option_mark

    now = datetime.now(UTC)
    proto_legs = [
        {**dict(leg), "strike": k} for leg, k in zip(src_legs, new_strikes, strict=True)
    ]
    live_qs = _live_leg_quotes(trade.symbol, proto_legs)
    new_legs: list[dict] = []
    for leg in proto_legs:
        contracts = int(leg.get("contracts", 1) or 1)
        q = _live_leg_quote(live_qs, leg)
        px = (
            _pick_fill_price(q, str(leg.get("action", "buy")), contracts)
            if q is not None
            else 0.0
        )
        if px <= 0:
            one = dict(leg)
            px = abs(_default_option_mark(_FakeTrade(trade.symbol, [one]), spot, now))
        if px <= 0:
            raise HTTPException(503, f"can't price {leg.get('side')} {leg['strike']:g}")
        new_legs.append(
            {
                "side": leg["side"],
                "action": leg.get("action", "buy"),
                "strike": float(leg["strike"]),
                "expiry": leg.get("expiry", today.isoformat()),
                "contracts": contracts,
                "entry_price": round(float(px), 4),
            }
        )

    # MARGIN — the post-swap book must fit: committed − old requirement +
    # new requirement ≤ balance. Checked BEFORE the close so a refused roll
    # never leaves the trader flat. Same shared gate as every open path
    # (review wave 10: the inline duplicate is gone) — release_legs credits
    # the position being swapped out.
    _require_buying_power(
        session,
        combine,
        trade.symbol,
        new_legs,
        float(spot),
        snap=snap,
        release_legs=src_legs,
    )

    realized = _close_one(session, trade, spot, now, "manual")
    if realized is None:
        raise HTTPException(409, "position closed concurrently — nothing to roll")
    trade.notes = (trade.notes or "") + f" · rolled {shift:+g}"

    net = compute_net_debit_credit([TradeLeg(**leg) for leg in new_legs])
    rolled = Trade(
        symbol=trade.symbol,
        strategy=trade.strategy,
        entry_date=now,
        entry_underlying_price=float(spot),
        net_debit_credit=net,
        status="open",
        trail_amount=trade.trail_amount,
        trail_pct=trade.trail_pct,
        tp_premium_mult=trade.tp_premium_mult,
        sl_premium_mult=trade.sl_premium_mult,
        is_paper=True,
        notes=f"rolled from #{trade.id} ({shift:+g})",
        tier=combine.tier,
        combine_id=combine.id,
    )
    rolled.legs = new_legs
    rolled.tags = ["0dte", "rolled"]
    rolled.mistake_tags = []
    session.add(rolled)
    session.flush()
    mirror_open(session, combine, rolled)
    session.commit()
    session.refresh(rolled)
    return RollOut(
        closed=trade.id,
        opened=rolled.id,
        realized=float(realized),
        net_debit_credit=float(rolled.net_debit_credit),
    )


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
