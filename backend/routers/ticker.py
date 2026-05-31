"""Ticker endpoints — price header (Phase 2), chart + metrics (Phase 3)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from calculations.expected_move import (
    atm_straddle_price,
    expected_move,
    expected_move_bands,
)
from calculations.gamma_exposure import (
    gamma_flip,
    gex_by_strike,
    largest_oi_strike,
    max_pain,
)
from calculations.iv_metrics import iv_percentile, vrp
from calculations.pc_ratio import pc_ratio
from calculations.realized_vol import realized_vol
from calculations.skew import skew_25d
from calculations.types import ContractRow
from database import SessionLocal
from models.options_snapshot import OptionsSnapshot
from schemas.ticker import (
    BarPoint,
    ChartAnnotations,
    ChartResponse,
    MetricsResponse,
    TickerDetailOut,
    WallLevel,
)
from services.alpaca_client import (
    get_bars,
    get_chain_snapshot,
    get_quotes,
    get_year_bars,
)
from services.cache import cache
from services.finnhub_client import next_earnings_for

router = APIRouter(prefix="/api/ticker", tags=["ticker"])
log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_TRADING_YEAR = 252
_AVG_VOL_WINDOW = 20

# Window for picking the near-term expiry that drives EM + skew. We skip
# 0–4 DTE (gamma-dominated noise) and prefer the first weekly/monthly out
# to ~45 days. Falls back to nearest available if nothing matches.
_NEAR_TERM_MIN_DTE = 5
_NEAR_TERM_MAX_DTE = 60

_IV_HISTORY_WINDOW = 60  # days needed before iv_percentile populates


# -- Phase 2: detail ---------------------------------------------------------


@router.get("/{symbol}/detail", response_model=TickerDetailOut)
def get_ticker_detail(symbol: str) -> TickerDetailOut:
    symbol = symbol.upper()

    quote = get_quotes([symbol]).get(symbol)
    if quote is None:
        raise HTTPException(status_code=404, detail=f"no quote available for {symbol}")

    bars = get_year_bars(symbol)
    if bars:
        recent = bars[-_TRADING_YEAR:]
        fifty_two_week_high = max(b.high for b in recent)
        fifty_two_week_low = min(b.low for b in recent)
        last_n = recent[-_AVG_VOL_WINDOW:]
        avg_volume_20d = (
            int(sum(b.volume for b in last_n) / len(last_n)) if last_n else 0
        )
    else:
        log.warning("year bars unavailable for %s; falling back to snapshot", symbol)
        fifty_two_week_high = quote.day_high or quote.price
        fifty_two_week_low = quote.day_low or quote.price
        avg_volume_20d = quote.day_volume

    next_er = next_earnings_for(symbol)
    days_to_er: int | None = None
    if next_er:
        try:
            er_date = datetime.fromisoformat(next_er).date()
            days_to_er = (er_date - datetime.now(_ET).date()).days
        except ValueError:
            log.warning("bad earnings date format for %s: %r", symbol, next_er)

    return TickerDetailOut(
        symbol=symbol,
        price=quote.price,
        change_dollar=quote.change_dollar,
        change_pct=quote.change_pct,
        day_high=quote.day_high or quote.price,
        day_low=quote.day_low or quote.price,
        fifty_two_week_high=fifty_two_week_high,
        fifty_two_week_low=fifty_two_week_low,
        volume=quote.day_volume,
        avg_volume_20d=avg_volume_20d,
        next_earnings_date=next_er,
        days_to_earnings=days_to_er,
    )


# -- Phase 3: chart + metrics -----------------------------------------------


def _fetch_bars(symbol: str, timeframe: str) -> list[BarPoint]:
    """Bars-only fetch. Separated so the bars path doesn't block on the
    options-chain fetch that drives annotations — see split below."""
    bars = get_bars(symbol, timeframe) or []
    if not bars:
        raise HTTPException(status_code=404, detail=f"no bars for {symbol} @ {timeframe}")
    return [
        BarPoint(
            t=b.timestamp.isoformat(),
            o=float(b.open),
            h=float(b.high),
            l=float(b.low),
            c=float(b.close),
            v=int(b.volume or 0),
        )
        for b in bars
    ]


@router.get("/{symbol}/bars", response_model=ChartResponse)
def get_ticker_bars(symbol: str, timeframe: str = "5m") -> ChartResponse:
    """Lightweight bars-only endpoint. Returns the same envelope as
    /chart for schema reuse but with empty annotations and a "bars" oi
    source — used by the frontend's fast-path chart query so candles
    aren't blocked behind a 1–3s options chain fetch.

    The annotations (max-pain, walls, EM bands) come from /chart in a
    second parallel query and overlay onto the chart as they arrive."""
    symbol = symbol.upper()
    cache_key = f"bars:{symbol}:{timeframe}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    bar_points = _fetch_bars(symbol, timeframe)
    response = ChartResponse(
        symbol=symbol,
        timeframe=timeframe,
        bars=bar_points,
        annotations=ChartAnnotations(),
        oi_source="bars_only",
    )
    cache.set(cache_key, response, ttl_seconds=30)
    return response


@router.get("/{symbol}/chart", response_model=ChartResponse)
def get_ticker_chart(symbol: str, timeframe: str = "5m") -> ChartResponse:
    """Full chart payload — bars PLUS annotations (EM, walls, max pain,
    gamma flip). Kept for backward compat and for the annotation overlay
    query; the frontend's fast-path chart uses /bars and overlays the
    annotations from THIS endpoint asynchronously."""
    symbol = symbol.upper()
    cache_key = f"chart:{symbol}:{timeframe}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    bar_points = _fetch_bars(symbol, timeframe)

    quote = get_quotes([symbol]).get(symbol)
    spot = quote.price if quote else float(bar_points[-1].c)

    chain, oi_source = _chain_with_oi_proxy(symbol)
    annotations = _compute_annotations(chain, spot)
    annotations.earnings_date = next_earnings_for(symbol)

    response = ChartResponse(
        symbol=symbol,
        timeframe=timeframe,
        bars=bar_points,
        annotations=annotations,
        oi_source=oi_source,
    )
    cache.set(cache_key, response, ttl_seconds=30)
    return response


@router.get("/{symbol}/metrics", response_model=MetricsResponse)
def get_ticker_metrics(symbol: str) -> MetricsResponse:
    symbol = symbol.upper()
    cache_key = f"metrics:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    chain, _ = _chain_with_oi_proxy(symbol)
    near = _pick_near_term_expiry(chain) if chain else None

    # IV30 — average IV across the near-term expiry's ATM-adjacent contracts.
    quote = get_quotes([symbol]).get(symbol)
    spot = quote.price if quote else None
    iv30 = _atm_iv(chain, near, spot) if (chain and near and spot is not None) else None

    # VRP needs IV30 and 30-day realized vol
    vrp_value: float | None = None
    if iv30 is not None:
        year_bars = get_year_bars(symbol)
        if year_bars and len(year_bars) >= 31:
            closes = [float(b.close) for b in year_bars[-60:]]
            rv = realized_vol(closes, window=30)
            if rv is not None:
                vrp_value = vrp(iv30 * 100, rv)  # iv30 is fraction; RV is %

    # Skew at near-term expiry
    sk = skew_25d(chain, near) if (chain and near) else None

    # P/C ratio from chain volumes (Alpaca free-tier sums daily volume)
    call_vol = sum(c.volume or 0 for c in chain or [] if c.type == "call")
    put_vol = sum(c.volume or 0 for c in chain or [] if c.type == "put")
    pc = pc_ratio(call_vol, put_vol)

    mp = max_pain(chain) if chain else None

    iv_rank_value, iv_status = _iv_rank_with_status(symbol, iv30)

    response = MetricsResponse(
        iv_rank=iv_rank_value,
        iv_rank_status=iv_status,
        vrp=vrp_value,
        skew_25d=sk,
        pc_ratio=pc,
        max_pain=mp,
    )
    cache.set(cache_key, response, ttl_seconds=30)
    return response


# -- helpers ----------------------------------------------------------------


def _chain_with_oi_proxy(symbol: str) -> tuple[list[ContractRow] | None, str]:
    """Return (chain, oi_source) where missing open_interest is filled from volume.

    Free-tier indicative feed returns no OI; volume is the best available proxy
    so the wall / max-pain / GEX computations don't all degrade to None.
    """
    chain = get_chain_snapshot(symbol, with_volume=True)
    if not chain:
        return None, "open_interest"

    has_native_oi = any(c.open_interest for c in chain)
    if has_native_oi:
        return chain, "open_interest"

    for c in chain:
        if c.open_interest is None and c.volume is not None:
            c.open_interest = c.volume
    return chain, "volume_proxy"


def _compute_annotations(
    chain: list[ContractRow] | None, spot: float
) -> ChartAnnotations:
    a = ChartAnnotations()
    if not chain:
        return a

    near = _pick_near_term_expiry(chain)
    if near is not None:
        straddle = atm_straddle_price(chain, spot, near)
        if straddle is not None:
            em = expected_move(*straddle)
            upper, lower = expected_move_bands(spot, em)
            a.expected_move_upper = upper
            a.expected_move_lower = lower

    cw = largest_oi_strike(chain, "call")
    if cw is not None:
        a.call_wall = WallLevel(strike=cw[0], oi=cw[1])
    pw = largest_oi_strike(chain, "put")
    if pw is not None:
        a.put_wall = WallLevel(strike=pw[0], oi=pw[1])

    a.max_pain = max_pain(chain)

    # Restrict the GEX walk to strikes within ±20% of spot. Deep OTM strikes
    # with tiny actual liquidity but non-trivial volume-proxy values would
    # otherwise dominate the cumulative sum and produce an absurd flip level
    # (e.g. $20 on a $235 stock).
    gex_window = [c for c in chain if 0.8 * spot <= c.strike <= 1.2 * spot]
    gex = gex_by_strike(gex_window, spot)
    a.gamma_flip = gamma_flip(gex) if gex else None

    return a


def _pick_near_term_expiry(chain: Iterable[ContractRow]) -> date | None:
    today = datetime.now(_ET).date()
    expiries = sorted({c.expiry for c in chain})
    in_window = [e for e in expiries if _NEAR_TERM_MIN_DTE <= (e - today).days <= _NEAR_TERM_MAX_DTE]
    if in_window:
        return in_window[0]
    # Fallback: nearest expiry that's at least today
    future = [e for e in expiries if e >= today]
    return future[0] if future else None


def _atm_iv(
    chain: Iterable[ContractRow], expiry: date, spot: float
) -> float | None:
    """Mean IV of the call+put pair at the strike closest to spot."""
    same = [c for c in chain if c.expiry == expiry]
    strikes = sorted({c.strike for c in same})
    if not strikes:
        return None
    atm = min(strikes, key=lambda k: abs(k - spot))
    ivs = [c.iv for c in same if c.strike == atm and c.iv is not None]
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def _iv_rank_with_status(symbol: str, iv30: float | None) -> tuple[float | None, str | None]:
    if iv30 is None:
        return None, "no IV available"
    history = _historical_iv30(symbol)
    n = len(history)
    if n < _IV_HISTORY_WINDOW:
        return None, f"{n}/{_IV_HISTORY_WINDOW} days collected"
    return iv_percentile(iv30, history), None


def _historical_iv30(symbol: str) -> list[float]:
    """Pull historical ATM IV per snapshot_date from options_snapshots.

    Uses median ATM IV per day to ride out outliers in the indicative feed.
    Empty until `collect_options_chain` has run for at least one day.
    """
    with SessionLocal() as session:
        return _historical_iv30_query(session, symbol)


def _historical_iv30_query(session: Session, symbol: str) -> list[float]:
    cutoff = datetime.now(_ET).date() - timedelta(days=_IV_HISTORY_WINDOW * 2)
    rows = session.execute(
        select(OptionsSnapshot.snapshot_date, OptionsSnapshot.iv)
        .where(OptionsSnapshot.symbol == symbol)
        .where(OptionsSnapshot.iv.is_not(None))
        .where(OptionsSnapshot.snapshot_date >= cutoff)
    ).all()
    by_date: dict[date, list[float]] = {}
    for snap_date, iv in rows:
        by_date.setdefault(snap_date, []).append(float(iv))
    daily_medians = []
    for d in sorted(by_date):
        vals = sorted(by_date[d])
        daily_medians.append(vals[len(vals) // 2])
    return daily_medians
