"""ZERO-DTE — chain lookup, paper-open, and (legacy) mark endpoint.

Three endpoints:

  GET  /api/zerodte/chain?symbol=  ATM call+put for the symbol expiring today
  POST /api/zerodte/open            create a paper long_straddle Trade record
  POST /api/zerodte/mark            (legacy) reprice + breakevens at scrubbed T

After the chart-integration step, the FRONT-END drives 0DTE through the
existing position pipeline: /open creates a Trade, and the chart's
existing analytics endpoint (/api/journal/trades/{id}/analytics) is what
polls for the live mark and intraday breakevens. /mark is kept for the
legacy ZeroDtePage (unlinked from the rail but still on disk).

Intraday BS math lives in calculations/intraday_analytics — shared with
the journal router's 0DTE branch. The engine file (black_scholes.py)
remains frozen.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from calculations.black_scholes import bs_greeks
from calculations.intraday_analytics import (
    SECONDS_PER_YEAR,
    bs_intraday,
    iv_intraday,
)
from calculations.position_analytics import DEFAULT_IV
from database import get_session
from models.account_state import AccountState
from models.trade import Trade
from schemas.journal import TradeOut, compute_net_debit_credit
from services.alpaca_client import get_chain_snapshot, get_quotes
from services.fred_client import latest_dgs3mo_rate
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
    """The next 4:00pm ET. If today's close has passed (after-hours,
    weekends) we still anchor to TODAY's close so the prototype clock
    is well-defined — the scrubber just starts in the "expired" state
    and the user can scrub backwards conceptually if needed. In
    practice the demo is used during the session, so this matters
    rarely. Keeps the math single-branch."""
    now = reference or datetime.now(_ET)
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
    indicative: bool = True
    notice: str = "Paper · indicative pricing (approximate)"


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
    source is "ask"/"mid"/"last" — only used internally; the API
    surfaces "quote" vs "bs" externally."""
    if c.ask and c.ask > 0:
        return float(c.ask), "ask"
    if c.bid and c.ask and c.bid > 0 and c.ask > 0:
        return (float(c.bid) + float(c.ask)) / 2, "mid"
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
    so the endpoint adds ~1ms on a warm cache."""
    sym = symbol.upper().strip()
    chain = get_chain_snapshot(sym, with_volume=False)
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
        rate = 0.045
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

        # Display greeks via the existing engine — same inputs as the BS
        # price fallback above (spot, strike, T-to-close, rate, ATM IV).
        cg = bs_greeks(spot, k, t_close, rate, iv_used, "call")
        pg = bs_greeks(spot, k, t_close, rate, iv_used, "put")

        rows.append(
            ChainStrikeRow(
                strike=k,
                call_price=round(float(call_px), 4),
                call_source=call_source,
                call_open_interest=getattr(call, "open_interest", None) if call else None,
                put_price=round(float(put_px), 4),
                put_source=put_source,
                put_open_interest=getattr(put, "open_interest", None) if put else None,
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
    )


# ---------------------------------------------------------------------------
# Open endpoint — create a paper long_straddle Trade and return it
# ---------------------------------------------------------------------------


class OpenRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=16, default="SPY")
    contracts: int = Field(gt=0, le=100, default=1)
    # buy = long straddle (debit); sell = short straddle (credit). Same
    # strike/expiry on both legs either way.
    action: Literal["buy", "sell"] = "buy"


class OpenLegRequest(BaseModel):
    """Click-to-open from the chain table: a single call/put leg at the
    given strike, expiring today. `action` is buy (long) or sell (short).
    `entry_price` is whatever the UI displayed at click time so what the
    user clicked is what they get filled at."""

    symbol: str = Field(min_length=1, max_length=16)
    side: Literal["call", "put"]
    action: Literal["buy", "sell"] = "buy"
    strike: float = Field(gt=0)
    entry_price: float = Field(ge=0)
    contracts: int = Field(gt=0, le=100, default=1)


def _pick_fill_price(q: _LegQuote, action: str = "buy") -> float:
    """Indicative fill price.

    Buyers pay the ask (worst-case); sellers receive the bid (worst-case).
    Falls back to mid then last when only one side is quoted. Returns 0
    if no usable quote at all — caller turns that into a 503."""
    if action == "sell":
        if q.bid and q.bid > 0:
            return float(q.bid)
    else:
        if q.ask and q.ask > 0:
            return float(q.ask)
    if q.bid and q.ask and q.bid > 0 and q.ask > 0:
        return (float(q.bid) + float(q.ask)) / 2
    if q.last and q.last > 0:
        return float(q.last)
    return 0.0


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
    session: Session = Depends(get_session),
) -> TradeOut:
    """Open an ATM straddle on `symbol` expiring TODAY as a paper Trade.

    Direction:
      * action="buy"  → long straddle (debit) — profit on big move
      * action="sell" → short straddle (credit) — profit on stay-put

    Strict 0DTE — refuses to open if today's expiry isn't listed.
    Refuses to open if the NYSE session is not OPEN."""
    _require_market_open()
    sym, spot, expiry, atm, call_q, put_q = _resolve_atm_chain(payload.symbol)
    _require_today_expiry(expiry)

    action = payload.action
    call_price = _pick_fill_price(call_q, action)
    put_price = _pick_fill_price(put_q, action)
    if call_price == 0 or put_price == 0:
        raise HTTPException(503, f"{sym} indicative quotes unavailable at ATM {atm}")

    contracts = payload.contracts
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

    active_tier = _current_tier(session)
    trade = Trade(
        symbol=sym,
        strategy=strategy,
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=spot,
        net_debit_credit=net,
        status="open",
        is_paper=True,
        notes=notes,
        tier=active_tier,
    )
    trade.legs = legs_json
    trade.tags = ["0dte"]
    trade.mistake_tags = []
    session.add(trade)
    session.commit()
    session.refresh(trade)

    return _trade_to_out(trade)


@router.post("/open-leg", response_model=TradeOut, status_code=201)
def open_zerodte_leg(
    payload: OpenLegRequest,
    session: Session = Depends(get_session),
) -> TradeOut:
    """Open a single call OR put leg expiring TODAY at `strike`.

    Direction:
      * action="buy"  → long_call / long_put     (debit, pay premium)
      * action="sell" → short_call / short_put   (credit, collect premium)

    Strict 0DTE: today's expiry must be listed for `symbol`. Refuses to
    open if the NYSE session is not OPEN."""
    _require_market_open()
    sym = payload.symbol.upper().strip()
    chain = get_chain_snapshot(sym, with_volume=False)
    if not chain:
        raise HTTPException(503, f"{sym} options chain unavailable")
    today = datetime.now(_ET).date()
    same_day = [c for c in chain if c.expiry == today]
    if not same_day:
        raise HTTPException(
            status_code=409,
            detail=(
                f"0DTE-only: {sym} has no contracts expiring today "
                f"({today.isoformat()})."
            ),
        )
    target_expiry = today

    quote = get_quotes([sym]).get(sym)
    if quote is None:
        raise HTTPException(503, f"{sym} quote unavailable")
    spot = float(quote.price)

    if payload.entry_price <= 0:
        raise HTTPException(400, "entry_price must be > 0")

    action = payload.action
    side = payload.side
    if action == "buy":
        strategy = "long_call" if side == "call" else "long_put"
        notes = f"0DTE long {side} · indicative fill"
    else:
        strategy = "short_call" if side == "call" else "short_put"
        notes = f"0DTE short {side} · indicative credit"

    leg_json = {
        "side": side,
        "action": action,
        "strike": float(payload.strike),
        "expiry": target_expiry.isoformat(),
        "contracts": payload.contracts,
        "entry_price": round(float(payload.entry_price), 4),
    }
    from schemas.journal import TradeLeg
    net = compute_net_debit_credit([TradeLeg(**leg_json)])

    active_tier = _current_tier(session)
    trade = Trade(
        symbol=sym,
        strategy=strategy,
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=spot,
        net_debit_credit=net,
        status="open",
        is_paper=True,
        notes=notes,
        tier=active_tier,
    )
    trade.legs = [leg_json]
    trade.tags = ["0dte"]
    trade.mistake_tags = []
    session.add(trade)
    session.commit()
    session.refresh(trade)
    return _trade_to_out(trade)


def _current_tier(session: Session) -> str:
    """Look up the active combine tier from AccountState. Defaults to
    50K if no state row exists (fresh-install fallback).
    """
    state = session.get(AccountState, 1)
    return state.active_tier if state else "50K"


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
# Mark endpoint — reprice + breakevens at a (possibly scrubbed) time
# ---------------------------------------------------------------------------


class StraddlePosition(BaseModel):
    """Open paper straddle. Sent up by the frontend with every /mark
    request; backend is stateless about the position itself."""

    strike: float = Field(gt=0)
    entry_spot: float = Field(gt=0)
    entry_call_price: float = Field(ge=0)
    entry_put_price: float = Field(ge=0)
    entry_time_iso: str
    expiry_iso: str               # ISO date — today (or fallback)
    contracts: int = Field(gt=0, default=1)


class MarkRequest(BaseModel):
    position: StraddlePosition
    # Override for the scrubber. Hours ELAPSED since entry. When omitted,
    # backend uses wall-clock now.
    elapsed_hours_override: float | None = None
    # Optional spot override — lets the frontend pass the candle the
    # crosshair is on if we ever want what-if; for now we always use
    # the live SPY quote.
    spot_override: float | None = None


class MarkOut(BaseModel):
    spot: float
    iv_used: float
    t_years_now: float            # remaining
    elapsed_hours: float          # since entry
    decay_pct: float              # 0..1 fraction of session burned
    mark_call: float
    mark_put: float
    mark_total: float             # per-share value of the straddle now
    cost_basis: float             # per-share entry premium total
    upl_dollar: float             # contracts × 100 × (mark_total − cost_basis)
    breakevens_today: list[float]
    breakevens_expiration: list[float]
    session_close_iso: str


@router.post("/mark", response_model=MarkOut)
def get_mark(req: MarkRequest) -> MarkOut:
    pos = req.position

    # Live spot — for the prototype we always fetch fresh. spot_override
    # is reserved for a "what-if" UI we don't build yet.
    if req.spot_override is not None:
        spot = float(req.spot_override)
    else:
        quote = get_quotes(["SPY"]).get("SPY")
        if quote is None:
            raise HTTPException(503, "SPY quote unavailable")
        spot = float(quote.price)

    try:
        rate = latest_dgs3mo_rate()
    except Exception:  # noqa: BLE001
        rate = 0.045

    # Time math.
    entry_dt = datetime.fromisoformat(pos.entry_time_iso)
    if entry_dt.tzinfo is None:
        entry_dt = entry_dt.replace(tzinfo=_ET)
    else:
        entry_dt = entry_dt.astimezone(_ET)
    # The expiry date is "today" (or fallback). Convert to a 4pm ET dt.
    try:
        expiry_d = date.fromisoformat(pos.expiry_iso)
    except ValueError:
        expiry_d = datetime.now(_ET).date()
    expiry_dt = datetime.combine(expiry_d, time(*_CLOSE_HHMM), tzinfo=_ET)

    t_at_entry_years = max((expiry_dt - entry_dt).total_seconds(), 60.0) / SECONDS_PER_YEAR

    if req.elapsed_hours_override is not None:
        elapsed_hours = max(0.0, float(req.elapsed_hours_override))
        elapsed_seconds = elapsed_hours * 3600
    else:
        now_et = datetime.now(_ET)
        elapsed_seconds = max(0.0, (now_et - entry_dt).total_seconds())
        elapsed_hours = elapsed_seconds / 3600

    # Remaining T from entry-time perspective.
    remaining_seconds = max(60.0, (expiry_dt - entry_dt).total_seconds() - elapsed_seconds)
    t_years_now = remaining_seconds / SECONDS_PER_YEAR

    # Session decay percentage — same denominator as the entry T so the
    # bar fills 0 → 100% as the scrubber sweeps entry → close.
    total_seconds_to_expiry_at_entry = max(60.0, (expiry_dt - entry_dt).total_seconds())
    decay_pct = min(1.0, elapsed_seconds / total_seconds_to_expiry_at_entry)

    # IV — back-solve from the entry call+put. Median of the two; if
    # either fails (e.g. entry price exactly zero), fall back to the
    # other or to DEFAULT_IV. Same defensive pattern as the rest of
    # position_analytics.
    iv_call = iv_intraday(
        pos.entry_call_price, pos.entry_spot, pos.strike,
        t_at_entry_years, rate, "call",
    )
    iv_put = iv_intraday(
        pos.entry_put_price, pos.entry_spot, pos.strike,
        t_at_entry_years, rate, "put",
    )
    candidates = [v for v in (iv_call, iv_put) if v is not None]
    iv_used = (sum(candidates) / len(candidates)) if candidates else DEFAULT_IV

    # Reprice both legs at the current (scrubbed) T.
    mark_call = bs_intraday(spot, pos.strike, t_years_now, rate, iv_used, "call")
    mark_put = bs_intraday(spot, pos.strike, t_years_now, rate, iv_used, "put")
    mark_total = mark_call + mark_put
    cost_basis = pos.entry_call_price + pos.entry_put_price
    upl_dollar = (mark_total - cost_basis) * pos.contracts * 100

    # Today's breakevens — where the straddle's CURRENT value across
    # spot equals the cost basis. Grid scan ±10% around the strike.
    grid_lo = pos.strike * 0.90
    grid_hi = pos.strike * 1.10
    prices = np.linspace(grid_lo, grid_hi, 101)
    pnl_today = np.empty_like(prices)
    for i, s in enumerate(prices):
        c = bs_intraday(float(s), pos.strike, t_years_now, rate, iv_used, "call")
        p = bs_intraday(float(s), pos.strike, t_years_now, rate, iv_used, "put")
        pnl_today[i] = (c + p) - cost_basis
    bes_today = _zero_crossings(prices, pnl_today)

    # Expiration BEs — kink at strike ± total premium. Compute analytically
    # so we don't depend on the grid resolution.
    bes_expiration = sorted([pos.strike - cost_basis, pos.strike + cost_basis])

    return MarkOut(
        spot=spot,
        iv_used=iv_used,
        t_years_now=t_years_now,
        elapsed_hours=elapsed_hours,
        decay_pct=decay_pct,
        mark_call=mark_call,
        mark_put=mark_put,
        mark_total=mark_total,
        cost_basis=cost_basis,
        upl_dollar=upl_dollar,
        breakevens_today=bes_today,
        breakevens_expiration=bes_expiration,
        session_close_iso=expiry_dt.isoformat(),
    )


def _zero_crossings(prices: np.ndarray, pnl: np.ndarray) -> list[float]:
    """Linear-interpolated zero crossings over a sampled curve."""
    out: list[float] = []
    for i in range(len(pnl) - 1):
        a, b = float(pnl[i]), float(pnl[i + 1])
        if a == 0:
            out.append(float(prices[i]))
        elif a * b < 0:
            t = a / (a - b)
            out.append(float(prices[i] + t * (prices[i + 1] - prices[i])))
    return out
