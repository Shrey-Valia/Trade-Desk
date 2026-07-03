"""Live 0DTE-availability check for ticker search.

Replaces the prior hardcoded `symbol in settings.zero_dte_universe`
flag with a real check against Alpaca's option contracts endpoint.

Uses `TradingClient.get_option_contracts(expiration_date=today_et,
underlying_symbols=[sym], limit=1)` — a single lightweight call per
symbol that returns at most one contract row if any same-day-expiry
contract is listed. Cached 5 minutes per symbol so rapid typing on
the search field doesn't hammer Alpaca, and so the result is shared
across multiple search-result hits within the same minute.

Performance note: the call is bounded by Alpaca's per-request limit
(default 100 with `limit=1`) and ~50-300ms warm. ThreadPoolExecutor
fan-out parallelizes the per-result checks so a 10-result search
worst-case is ~1 wall-second on a cold cache.

Failure modes:
  - Alpaca unreachable / timeout → log WARN, return False (no badge),
    but cache the False only briefly (_ERROR_TTL_S): an error is NOT
    the fact "no 0DTE exists today". A 5-minute negative cache here
    once hid the badge on SPY/QQQ — the product's core instruments —
    for the whole window after one slow patch.
  - Symbol with no listed options → empty contract list → False,
    cached for the full TTL (a real negative result).
  - Symbol not found / delisted → empty list or 404 → False.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus
from alpaca.trading.requests import GetOptionContractsRequest

from config import settings
from services.cache import cache

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_CACHE_TTL_S = 300  # 5 minutes per symbol — real (non-error) results only
_ERROR_TTL_S = 20  # transient failures re-probe quickly


def _trading_client() -> TradingClient:
    return TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_api_secret,
        paper=settings.alpaca_paper,
    )


def _today_et_iso() -> str:
    return datetime.now(_ET).date().isoformat()


def has_zero_dte(symbol: str) -> bool:
    """True iff there is at least one option contract on `symbol`
    that expires today (NY date). Cached 5 minutes per symbol.

    Never raises. On error returns False and caches the False so
    repeated queries on a flaky path don't pile up.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return False

    today_iso = _today_et_iso()
    cache_key = f"has_0dte:{sym}:{today_iso}"
    cached = cache.get(cache_key)
    if cached is not None:
        return bool(cached)

    try:
        client = _trading_client()
        req = GetOptionContractsRequest(
            underlying_symbols=[sym],
            status=AssetStatus.ACTIVE,
            expiration_date=datetime.now(_ET).date(),
            limit=1,
        )
        resp = client.get_option_contracts(req)
        contracts = getattr(resp, "option_contracts", None) or []
        result = len(contracts) > 0
    except Exception as exc:  # noqa: BLE001
        # An error is not a negative result — short TTL so the badge
        # comes back as soon as the feed recovers.
        log.warning("has_zero_dte(%s) failed: %s", sym, exc)
        cache.set(cache_key, False, ttl_seconds=_ERROR_TTL_S)
        return False

    cache.set(cache_key, result, ttl_seconds=_CACHE_TTL_S)
    return result


def has_zero_dte_bulk(symbols: list[str]) -> dict[str, bool]:
    """Parallel fan-out over `symbols` with the per-symbol cache.

    Used by the search router to badge ≤10 result hits without
    bottlenecking the response on sequential round-trips. Each
    symbol uses the same caching as has_zero_dte().

    Wall-clock budget: ~1s for a 10-result query on a fully cold
    cache (Alpaca per-call ~200-500ms, 8 workers).
    """
    if not symbols:
        return {}
    # Quick filter: symbols already cached as True/False resolve
    # synchronously without spinning up worker threads.
    out: dict[str, bool] = {}
    cold: list[str] = []
    today_iso = _today_et_iso()
    for sym in symbols:
        s = sym.strip().upper()
        if not s:
            continue
        cached = cache.get(f"has_0dte:{s}:{today_iso}")
        if cached is not None:
            out[s] = bool(cached)
        else:
            cold.append(s)
    if not cold:
        return out

    # Parallel fetch for cold misses. ThreadPoolExecutor since the
    # underlying alpaca-py call is blocking I/O.
    from concurrent.futures import ThreadPoolExecutor

    max_workers = min(8, len(cold))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        # Per-symbol deadline (not one shared wall-clock: a shared budget
        # starved the later futures — remaining≈0 — so SPY/QQQ could be
        # negative-cached off a queue position, not a real answer).
        futures = {ex.submit(has_zero_dte, s): s for s in cold}
        for fut, s in futures.items():
            try:
                out[s] = fut.result(timeout=2.0)
            except Exception as exc:  # noqa: BLE001
                log.warning("has_zero_dte_bulk(%s) timed out / failed: %s", s, exc)
                out[s] = False
                # A timeout is an ERROR, not "no 0DTE today" — short TTL
                # so the next keystroke after recovery re-probes.
                cache.set(
                    f"has_0dte:{s}:{today_iso}", False, ttl_seconds=_ERROR_TTL_S,
                )
    return out
