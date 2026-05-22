"""Wrapper around the modern alpaca-py SDK.

NOTE: this uses `alpaca-py` (the maintained package) — never the legacy
`alpaca-trade-api`. All imports come from `alpaca.data.*`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import (
    OptionBarsRequest,
    OptionChainRequest,
    StockBarsRequest,
    StockSnapshotRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from calculations.types import ContractRow
from config import settings
from services.cache import cache

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
# Per-request chunk for option bars. Alpaca accepts large batches but URL
# length grows fast with 21-char OCC symbols — 100 keeps us comfortably under.
_BAR_CHUNK = 100

# Regular trading hours used for the 1D chart filter. Pre-market on the free
# IEX feed is mostly empty so we'd just be drawing flat noise. Promote to a
# config flag if/when we add an extended-hours toggle.
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


@dataclass
class Quote:
    """A live quote with the data needed for a watchlist row + price header.

    `price` is the latest trade (what people expect to see).
    `prev_close` is yesterday's daily close — the denominator for the
    universal "+1.82%" day-change convention used everywhere.
    `day_*` fields come from the snapshot's daily_bar (today's session
    so far). Default to 0 when the snapshot has no daily_bar yet (e.g.
    pre-market with no trades).
    """

    symbol: str
    price: float
    prev_close: float
    day_high: float = 0.0
    day_low: float = 0.0
    day_volume: int = 0

    @property
    def change_pct(self) -> float:
        if self.prev_close == 0:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100

    @property
    def change_dollar(self) -> float:
        return self.price - self.prev_close


def _stock_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_api_secret)


def _option_client() -> OptionHistoricalDataClient:
    return OptionHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_api_secret)


def get_quotes(symbols: list[str]) -> dict[str, Quote]:
    """Latest trade + previous daily close for each symbol — one batched call.

    Cached for 5s so concurrent consumers (the refresh job + an ad-hoc API
    request) don't double-hit Alpaca for the same payload.

    Tickers whose `previous_daily_bar` comes back missing (IPOs, halts,
    feed glitches) get logged and skipped — we'd rather lose one row than
    crash the whole refresh.
    """
    cache_key = f"alpaca:snapshots:{','.join(sorted(symbols))}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    client = _stock_client()
    req = StockSnapshotRequest(symbol_or_symbols=symbols)
    raw = client.get_stock_snapshot(req)

    out: dict[str, Quote] = {}
    for symbol, snap in raw.items():
        latest_trade = getattr(snap, "latest_trade", None)
        prev_bar = getattr(snap, "previous_daily_bar", None)
        if latest_trade is None or prev_bar is None or prev_bar.close in (None, 0):
            log.warning(
                "snapshot missing trade/prev_close for %s (trade=%s, prev_bar=%s)",
                symbol,
                latest_trade is not None,
                prev_bar is not None,
            )
            continue
        daily_bar = getattr(snap, "daily_bar", None)
        out[symbol] = Quote(
            symbol=symbol,
            price=float(latest_trade.price),
            prev_close=float(prev_bar.close),
            day_high=float(getattr(daily_bar, "high", 0) or 0) if daily_bar else 0.0,
            day_low=float(getattr(daily_bar, "low", 0) or 0) if daily_bar else 0.0,
            day_volume=int(getattr(daily_bar, "volume", 0) or 0) if daily_bar else 0,
        )

    cache.set(cache_key, out, ttl_seconds=5)
    return out


def get_year_bars(symbol: str) -> list | None:
    """1 year of daily bars for one symbol. Cached 24h, keyed by ET date.

    Pulls 365 calendar days back so consumers can slice the trailing 252
    trading days without missing any. Cache key includes today's ET date,
    so a fresh fetch happens automatically on the first request of each
    market day; old keys naturally drop out of the in-process cache.
    """
    today_et = datetime.now(_ET).date()
    cache_key = f"alpaca:bars1y:{symbol}:{today_et.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    start = datetime.combine(today_et - timedelta(days=365), time.min, tzinfo=_ET)
    client = _stock_client()
    try:
        bars = client.get_stock_bars(
            StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start,
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("year bars fetch failed for %s: %s", symbol, exc)
        return None

    data = getattr(bars, "data", None) or {}
    bar_list = list(data.get(symbol, []))
    bar_list.sort(key=lambda b: b.timestamp)

    cache.set(cache_key, bar_list, ttl_seconds=86400)
    return bar_list


def get_option_chain_volumes(symbol: str) -> tuple[int, int] | None:
    """Returns (total_call_volume, total_put_volume) across the whole chain.

    OptionsSnapshot has no daily_bar (that's stock-only), so we:
      1. Fetch the chain to enumerate OCC symbols and classify by side
      2. Issue OptionBarsRequest(timeframe=Day, start=today) for true volume
      3. Fall back to summing latest_trade.size from the chain if bars fail

    Cached 5min — chain + bars are heavy and the indicative feed isn't
    truly real-time on the free tier anyway.
    """
    cache_key = f"alpaca:chain_vol:{symbol}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    chain = _fetch_chain(symbol)
    if chain is None:
        return None

    call_symbols: list[str] = []
    put_symbols: list[str] = []
    fallback_call_size = 0
    fallback_put_size = 0
    for occ_symbol, snapshot in chain.items():
        side = _occ_side(occ_symbol)
        if side is None:
            continue
        if side == "call":
            call_symbols.append(occ_symbol)
        else:
            put_symbols.append(occ_symbol)
        # Sum latest_trade.size for the fallback path while we're walking the chain.
        latest_trade = getattr(snapshot, "latest_trade", None)
        size = int(getattr(latest_trade, "size", 0) or 0) if latest_trade else 0
        if side == "call":
            fallback_call_size += size
        else:
            fallback_put_size += size

    today_start = datetime.combine(datetime.now(_ET).date(), time.min, tzinfo=_ET)

    try:
        call_vol = _sum_today_volume(call_symbols, today_start)
        put_vol = _sum_today_volume(put_symbols, today_start)
        result = (call_vol, put_vol)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "option bars fetch failed for %s, using latest_trade.size fallback: %s",
            symbol,
            exc,
        )
        result = (fallback_call_size, fallback_put_size)

    cache.set(cache_key, result, ttl_seconds=300)
    return result


def _fetch_chain(symbol: str):
    client = _option_client()
    req = OptionChainRequest(underlying_symbol=symbol, feed=settings.alpaca_options_feed)
    try:
        return client.get_option_chain(req)
    except Exception as exc:  # noqa: BLE001
        log.warning("alpaca chain fetch failed for %s: %s", symbol, exc)
        return None


def _occ_side(occ_symbol: str) -> str | None:
    """OCC: ROOT + YYMMDD + C/P + STRIKE×1000 (8 digits). Side is 9 chars from end."""
    if len(occ_symbol) < 9:
        return None
    type_char = occ_symbol[-9:-8]
    if type_char == "C":
        return "call"
    if type_char == "P":
        return "put"
    return None


def _sum_today_volume(occ_symbols: list[str], start: datetime) -> int:
    if not occ_symbols:
        return 0
    client = _option_client()
    total = 0
    for i in range(0, len(occ_symbols), _BAR_CHUNK):
        chunk = occ_symbols[i : i + _BAR_CHUNK]
        req = OptionBarsRequest(
            symbol_or_symbols=chunk,
            timeframe=TimeFrame.Day,
            start=start,
        )
        bars = client.get_option_bars(req)
        # bars.data is dict[symbol, list[Bar]] in alpaca-py >= 0.30
        data = getattr(bars, "data", None) or {}
        for _, bar_list in data.items():
            for bar in bar_list:
                volume = getattr(bar, "volume", 0) or 0
                total += int(volume)
    return total


# ---------------------------------------------------------------------------
# Phase 3: full chain snapshot + timeframe-aware bars
# ---------------------------------------------------------------------------

# Sentinel used to cache "we tried and got nothing" results so 5s frontend
# polling can't hammer a failing endpoint. Treated as None on read.
_NEGATIVE = object()


def _parse_occ(occ_symbol: str) -> tuple[date, str, float] | None:
    """Decode an OCC option symbol into (expiry, side, strike).

    Format: ROOT + YYMMDD + C/P + STRIKE×1000 (8-digit padded).
    Returns None if the symbol is too short or malformed.
    """
    if len(occ_symbol) < 15:
        return None
    try:
        strike_int = int(occ_symbol[-8:])
        side_char = occ_symbol[-9:-8]
        date_str = occ_symbol[-15:-9]
        expiry = datetime.strptime(date_str, "%y%m%d").date()
    except ValueError:
        return None
    side = "call" if side_char == "C" else "put" if side_char == "P" else None
    if side is None:
        return None
    return expiry, side, strike_int / 1000.0


def get_chain_snapshot(symbol: str, with_volume: bool = True) -> list[ContractRow] | None:
    """Full options chain as ContractRow list. Cached 5min — successes AND misses.

    Caches the negative case (None / empty) for the same TTL so a ticker
    with no chain or a transient failure doesn't get re-hit on every 5s
    frontend poll.

    `with_volume=True` (default) issues a chunked OptionBarsRequest to also
    populate per-contract daily volume. Required because Alpaca's free
    indicative feed returns no open_interest field — chart-level walls /
    max-pain / GEX computations rely on volume as an OI proxy. Costs ~50
    extra API calls per fresh fetch on a 4800-contract chain like NVDA.
    """
    cache_key = f"alpaca:chain_snap:{symbol}:{int(with_volume)}"
    cached = cache.get(cache_key)
    if cached is _NEGATIVE:
        return None
    if cached is not None:
        return cached

    chain = _fetch_chain(symbol)
    if chain is None or len(chain) == 0:
        cache.set(cache_key, _NEGATIVE, ttl_seconds=300)
        return None

    rows: list[ContractRow] = []
    occ_to_index: dict[str, int] = {}
    for occ_symbol, snap in chain.items():
        parsed = _parse_occ(occ_symbol)
        if parsed is None:
            continue
        expiry, side, strike = parsed

        greeks = getattr(snap, "greeks", None)
        latest_quote = getattr(snap, "latest_quote", None)
        latest_trade = getattr(snap, "latest_trade", None)

        occ_to_index[occ_symbol] = len(rows)
        rows.append(
            ContractRow(
                strike=strike,
                expiry=expiry,
                type=side,
                iv=_safe_float(getattr(snap, "implied_volatility", None)),
                delta=_safe_float(getattr(greeks, "delta", None) if greeks else None),
                gamma=_safe_float(getattr(greeks, "gamma", None) if greeks else None),
                volume=None,
                open_interest=_safe_int(getattr(snap, "open_interest", None)),
                bid=_safe_float(getattr(latest_quote, "bid_price", None) if latest_quote else None),
                ask=_safe_float(getattr(latest_quote, "ask_price", None) if latest_quote else None),
                last=_safe_float(getattr(latest_trade, "price", None) if latest_trade else None),
            )
        )

    if not rows:
        cache.set(cache_key, _NEGATIVE, ttl_seconds=300)
        return None

    if with_volume:
        _populate_per_contract_volume(occ_to_index, rows)

    cache.set(cache_key, rows, ttl_seconds=300)
    return rows


def _populate_per_contract_volume(
    occ_to_index: dict[str, int], rows: list[ContractRow]
) -> None:
    """Fetch today's daily volume per OCC symbol and write into rows[i].volume."""
    today_start = datetime.combine(datetime.now(_ET).date(), time.min, tzinfo=_ET)
    occ_symbols = list(occ_to_index.keys())
    client = _option_client()
    for i in range(0, len(occ_symbols), _BAR_CHUNK):
        chunk = occ_symbols[i : i + _BAR_CHUNK]
        try:
            bars = client.get_option_bars(
                OptionBarsRequest(
                    symbol_or_symbols=chunk,
                    timeframe=TimeFrame.Day,
                    start=today_start,
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("per-contract volume fetch chunk failed: %s", exc)
            continue
        data = getattr(bars, "data", None) or {}
        for occ_symbol, bar_list in data.items():
            idx = occ_to_index.get(occ_symbol)
            if idx is None or not bar_list:
                continue
            volume = sum(int(getattr(b, "volume", 0) or 0) for b in bar_list)
            rows[idx].volume = volume


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# Timeframe configuration. Each entry: (TimeFrame, lookback_days, cache_ttl_s,
# rth_only). RTH filter only sensibly applies to the 1D minute view — for
# multi-day grains the boundary handling adds complexity for no visual gain.
_TIMEFRAME_CONFIG: dict[str, tuple[TimeFrame, int, int, bool]] = {
    "1D": (TimeFrame.Minute, 1, 60, True),
    "5D": (TimeFrame(15, TimeFrameUnit.Minute), 7, 300, False),
    "1M": (TimeFrame.Day, 35, 3600, False),
    "3M": (TimeFrame.Day, 100, 3600, False),
}


def get_bars(symbol: str, timeframe: str) -> list | None:
    """Bars sized to a chart timeframe. See _TIMEFRAME_CONFIG for the grid."""
    if timeframe not in _TIMEFRAME_CONFIG:
        log.warning("unknown timeframe %r, defaulting to 5D", timeframe)
        timeframe = "5D"
    tf, lookback_days, ttl, rth_only = _TIMEFRAME_CONFIG[timeframe]

    today_et = datetime.now(_ET).date()
    cache_key = f"alpaca:bars:{symbol}:{timeframe}:{today_et.isoformat()}"
    cached = cache.get(cache_key)
    if cached is _NEGATIVE:
        return None
    if cached is not None:
        return cached

    start = datetime.combine(today_et - timedelta(days=lookback_days), time.min, tzinfo=_ET)
    client = _stock_client()
    try:
        bars = client.get_stock_bars(
            StockBarsRequest(symbol_or_symbols=symbol, timeframe=tf, start=start)
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("get_bars failed for %s @ %s: %s", symbol, timeframe, exc)
        cache.set(cache_key, _NEGATIVE, ttl_seconds=ttl)
        return None

    data = getattr(bars, "data", None) or {}
    bar_list = list(data.get(symbol, []))
    bar_list.sort(key=lambda b: b.timestamp)

    if rth_only:
        bar_list = [b for b in bar_list if _is_rth(b.timestamp)]

    if not bar_list:
        cache.set(cache_key, _NEGATIVE, ttl_seconds=ttl)
        return None

    cache.set(cache_key, bar_list, ttl_seconds=ttl)
    return bar_list


def _is_rth(ts: datetime) -> bool:
    """True when `ts` falls within NYSE regular trading hours (ET)."""
    et = ts.astimezone(_ET)
    t = et.time()
    return RTH_OPEN <= t < RTH_CLOSE


def get_daily_bars_history(symbol: str, years_back: int = 5) -> list | None:
    """Daily bars going `years_back` years back. Cached 24h per (symbol, years).

    Used by the ML backfill — `get_year_bars` only goes 1y. This is a
    separate cache so the regular dashboard's 1y data isn't disturbed.
    """
    today_et = datetime.now(_ET).date()
    cache_key = f"alpaca:bars_history:{symbol}:{years_back}:{today_et.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    start = datetime.combine(
        today_et - timedelta(days=int(years_back * 366)), time.min, tzinfo=_ET
    )
    client = _stock_client()
    try:
        bars = client.get_stock_bars(
            StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start)
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("daily history fetch failed for %s: %s", symbol, exc)
        return None
    data = getattr(bars, "data", None) or {}
    bar_list = list(data.get(symbol, []))
    bar_list.sort(key=lambda b: b.timestamp)
    cache.set(cache_key, bar_list, ttl_seconds=86400)
    return bar_list
