"""Ticker endpoints — price header (Phase 2), chart + metrics (Phase 3)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
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
from calculations.technicals import atr, ema, rsi, sma, vwap
from calculations.types import ContractRow
from database import SessionLocal
from models.options_snapshot import OptionsSnapshot
from schemas.ticker import (
    BarPoint,
    ChartAnnotations,
    ChartResponse,
    IndicatorSeries,
    IndicatorsResponse,
    MetricsResponse,
    TickerDetailOut,
    WallLevel,
)
from services.alpaca_client import (
    bars_cache_ttl,
    MarketDataUnavailable,
    get_bars,
    get_chain_snapshot,
    get_quotes,
    get_year_bars,
)
from services.cache import cache
from services.finnhub_client import next_earnings_for
from services.resilience import breaker_retry_after

router = APIRouter(prefix="/api/ticker", tags=["ticker"])
log = logging.getLogger(__name__)

# Alpaca breaker name (kept in sync with services.alpaca_client._ALPACA).
# Drives the Retry-After header on the degraded chart response.
_ALPACA_BREAKER = "alpaca"
# Floor (seconds) for the degraded Retry-After hint. Before the breaker trips
# (fewer than its fail-threshold consecutive failures) breaker_retry_after
# returns ~1s, which would tell the client to retry straight back into a
# just-rate-limited key every second. A 5s floor keeps the early-degradation
# backoff meaningful; once the breaker opens, its ~30s cooldown dominates.
_MIN_DEGRADED_RETRY_S = 5


class MarketDataDegraded(HTTPException):
    """HTTP 503 raised when the market-data feed is degraded (circuit
    breaker open / rate-limited). Carries a `Retry-After` header and a
    JSON body the frontend keys on (`{"error": "market_data_unavailable",
    ...}`) to render an explicit "data unavailable — retrying" state with
    auto-retry instead of an infinite spinner or a bare 500."""

    def __init__(self) -> None:
        retry_after = max(_MIN_DEGRADED_RETRY_S, breaker_retry_after(_ALPACA_BREAKER))
        super().__init__(
            status_code=503,
            detail="market data temporarily unavailable — retrying",
            headers={"Retry-After": str(retry_after)},
        )
        self.retry_after = retry_after

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            headers={"Retry-After": str(self.retry_after)},
            content={
                "error": "market_data_unavailable",
                "detail": self.detail,
                "retry_after": self.retry_after,
            },
        )

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
    options-chain fetch that drives annotations — see split below.

    Raises MarketDataDegraded (503) when the upstream feed is circuit-open
    / rate-limited — distinct from a genuine "no bars" (404) so the
    frontend can show a retrying state instead of treating it as terminal.
    """
    try:
        bars = get_bars(symbol, timeframe) or []
    except MarketDataUnavailable:
        log.info("bars degraded for %s @ %s (circuit open / rate-limited)", symbol, timeframe)
        raise MarketDataDegraded() from None
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


# -- Phase: technical indicator overlays ------------------------------------

# Supported indicator FAMILIES. Each maps to
#   (label prefix, pane, parameterizable, default_period)
# where `parameterizable` says whether the period can be tuned per-request
# and `default_period` is used when the caller sends a bare family name.
# VWAP is cumulative (no window), so it carries no period.
_INDICATOR_FAMILIES: dict[str, tuple[str, str, bool, int | None]] = {
    "sma": ("SMA", "price", True, 20),
    "ema": ("EMA", "price", True, 50),
    "vwap": ("VWAP", "price", False, None),
    "rsi": ("RSI", "oscillator", True, 14),
    "atr": ("ATR", "volatility", True, 14),
}

# Window bounds — keep a tuned period sane and bound the work the math does.
_MIN_PERIOD = 2
_MAX_PERIOD = 400

_DEFAULT_INDICATOR_SET = "sma:20,ema:50,vwap,rsi:14,atr:14"


def _parse_token(token: str) -> tuple[str, int | None] | None:
    """Parse one indicator token into (family, period).

    Accepts both the new `name:period` form (e.g. `sma:20`, `rsi:9`) and the
    legacy `name<digits>` form (e.g. `sma20`, `rsi14`) plus a bare family
    name (`vwap`, or `sma` → default period). Returns None for unknown or
    malformed tokens (the caller skips them).
    """
    token = token.strip().lower()
    if not token:
        return None

    # name:period
    if ":" in token:
        name, _, raw = token.partition(":")
        family = _INDICATOR_FAMILIES.get(name)
        if family is None:
            return None
        _, _, parameterizable, default = family
        if not parameterizable:
            # e.g. "vwap:30" — ignore the bogus period, keep the family.
            return (name, None)
        try:
            period = int(raw)
        except ValueError:
            period = default if default is not None else 0
        return (name, _window_of(period))

    # bare family name (no period) → its default
    if token in _INDICATOR_FAMILIES:
        _, _, _, default = _INDICATOR_FAMILIES[token]
        return (token, default)

    # legacy name<digits> (e.g. sma20, rsi14)
    for name in _INDICATOR_FAMILIES:
        if token.startswith(name) and token[len(name):].isdigit():
            _, _, parameterizable, default = _INDICATOR_FAMILIES[name]
            if not parameterizable:
                return (name, None)
            return (name, _window_of(int(token[len(name):])))

    return None


def _window_of(period: int) -> int:
    """Clamp a requested period into the supported window range."""
    return max(_MIN_PERIOD, min(_MAX_PERIOD, period))


def _canonical_key(family: str, period: int | None) -> str:
    """The stable per-series key that goes in the cache key AND the returned
    `series[*].key`. Parameterizable families encode the period as
    `name:period`; VWAP stays bare. Keeping ONE canonical spelling makes the
    cache key insensitive to caller formatting (sma20 == sma:20) and gives
    the frontend a deterministic react-query key + color-family token."""
    if period is None:
        return family
    return f"{family}:{period}"


def _build_single(
    family: str, period: int | None, closes: list[float], bars: list
) -> list | None:
    """Dispatch one (family, period) to its calculation, using the
    REQUESTED period. Returns the per-bar series, or None if unrecognized."""
    if family == "vwap":
        return vwap(bars)
    if family == "sma":
        return sma(closes, period or 0)
    if family == "ema":
        return ema(closes, period or 0)
    if family == "rsi":
        return rsi(closes, period or 0)
    if family == "atr":
        return atr(bars, period or 0)
    return None


@router.get("/{symbol}/indicators", response_model=IndicatorsResponse)
def get_ticker_indicators(
    symbol: str,
    timeframe: str = "5m",
    # Wire name stays `set` (the frontend + existing tests send `?set=…`),
    # but the Python param is renamed so it doesn't shadow the `set` builtin
    # used inside the function.
    indicator_set: str = Query(_DEFAULT_INDICATOR_SET, alias="set"),
) -> IndicatorsResponse:
    """Per-bar technical-indicator arrays aligned to the SAME bars the
    /chart and /bars endpoints return.

    `set` is a comma-separated list of indicator tokens. Each token is
    either `name:period` (e.g. `sma:20,ema:50,rsi:9`) or the legacy
    `name<digits>` form (`sma20`,`rsi14`) or a bare family name (`vwap`,
    or `sma` → its default period). Unknown/malformed tokens are skipped.
    Each returned series is the same length as the bar array, with `None`
    in the warm-up region. Cached per (symbol, timeframe, normalized set):
    the PERIODS are part of the normalized set, so `sma:20` and `sma:50`
    are distinct cache entries."""
    symbol = symbol.upper()

    # Parse + canonicalize every token, dropping unknowns and de-duplicating
    # while preserving first-seen order. The canonical key encodes the period
    # so the cache key (built below) varies with the period — `sma:20` and
    # `sma:50` never collide.
    parsed: list[tuple[str, str, int | None]] = []  # (canonical_key, family, period)
    seen: set[str] = set()
    for raw in indicator_set.split(","):
        token = _parse_token(raw)
        if token is None:
            continue
        family, period = token
        key = _canonical_key(family, period)
        if key in seen:
            continue
        seen.add(key)
        parsed.append((key, family, period))

    norm_set = ",".join(k for k, _, _ in parsed)

    cache_key = f"indicators:{symbol}:{timeframe}:{norm_set}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Same degraded-feed handling as _fetch_bars: a circuit-open / rate-limited
    # feed surfaces as a typed 503 (retryable) rather than a bare 500, so the
    # indicator overlay degrades the same way the underlying chart does.
    try:
        bars = get_bars(symbol, timeframe) or []
    except MarketDataUnavailable:
        log.info("indicators degraded for %s @ %s (circuit open / rate-limited)", symbol, timeframe)
        raise MarketDataDegraded() from None
    if not bars:
        raise HTTPException(
            status_code=404, detail=f"no bars for {symbol} @ {timeframe}"
        )

    closes = [float(b.close) for b in bars]
    times = [b.timestamp.isoformat() for b in bars]

    series: list[IndicatorSeries] = []
    for key, family, period in parsed:
        values = _build_single(family, period, closes, bars)
        if values is None:
            continue
        label_prefix, pane, _, _ = _INDICATOR_FAMILIES[family]
        label = label_prefix if period is None else f"{label_prefix} {period}"
        series.append(
            IndicatorSeries(key=key, label=label, pane=pane, values=values)
        )

    response = IndicatorsResponse(
        symbol=symbol, timeframe=timeframe, times=times, series=series
    )
    cache.set(cache_key, response, ttl_seconds=bars_cache_ttl(timeframe))
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
