"""Live symbol catalog backed by Alpaca's assets endpoint.

The ticker search router used to ship a hardcoded 16-symbol list,
which meant "BABA" returned nothing and "AAPL" worked only because
it was in the hand-curated set. This service replaces that with the
full Alpaca active US-equity universe (~10,000+ symbols including
ETFs), refreshed daily.

Lifecycle:
  - `refresh()` fetches the assets list via TradingClient and stores
    a sorted-by-symbol tuple of CatalogEntry. Idempotent; safe to
    call from APScheduler.
  - `search(q, limit)` ranks substring matches by:
        3.0  exact symbol match
        2.0  symbol-prefix match
        1.0  symbol-substring match
        0.5  name-substring match
    Same scoring the router used before; runs against the live set.
  - `get_all()` is for diagnostics + tests.

Failure modes:
  - Alpaca unreachable or returns nothing → keep the previous catalog
    if one is loaded, else fall back to the bundled
    `_FALLBACK_CATALOG` (the 16 symbols the router shipped with).
    Log a WARN so the operator sees the degradation.
  - First call before `refresh()` has populated → returns results
    from the fallback so the endpoint is never empty.

The module exposes a process-wide single catalog. A single user
running locally doesn't need per-request isolation; we keep this
simple.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, AssetStatus
from alpaca.trading.requests import GetAssetsRequest

from config import settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogEntry:
    symbol: str
    name: str
    exchange: str


# Indices like SPX, NDX, VIX are NOT equities — they're cash-settled
# CBOE products with no Alpaca bars endpoint and no chain on the free
# tier. Letting them surface in search lets a user click a ticker that
# 404s the chart, the chain, and the detail panels. Filter them out at
# both the refresh path (in case Alpaca starts listing them as
# us_equity) and the search path (in case a fallback row sneaks in).
_INDEX_DENYLIST: frozenset[str] = frozenset(
    {"SPX", "NDX", "RUT", "VIX", "DJX", "OEX", "XSP", "XEO", "MXEF", "RUI"}
)


# Bundled fallback — used only when Alpaca hasn't populated yet AND
# we have no prior catalog (fresh boot before refresh completes).
# Mirrors the curated set the router shipped with, minus index tickers
# (those would 404 the chart endpoints if the user clicked them).
_FALLBACK_CATALOG: tuple[CatalogEntry, ...] = (
    CatalogEntry("SPY", "SPDR S&P 500 ETF", "ARCA"),
    CatalogEntry("QQQ", "Invesco QQQ Trust", "NASDAQ"),
    CatalogEntry("IWM", "iShares Russell 2000 ETF", "ARCA"),
    CatalogEntry("DIA", "SPDR Dow Jones Industrial Average ETF", "ARCA"),
    CatalogEntry("AAPL", "Apple Inc.", "NASDAQ"),
    CatalogEntry("MSFT", "Microsoft Corp.", "NASDAQ"),
    CatalogEntry("NVDA", "NVIDIA Corp.", "NASDAQ"),
    CatalogEntry("TSLA", "Tesla Inc.", "NASDAQ"),
    CatalogEntry("AMD", "Advanced Micro Devices", "NASDAQ"),
    CatalogEntry("GOOGL", "Alphabet Inc.", "NASDAQ"),
    CatalogEntry("AMZN", "Amazon.com Inc.", "NASDAQ"),
    CatalogEntry("META", "Meta Platforms Inc.", "NASDAQ"),
    CatalogEntry("NFLX", "Netflix Inc.", "NASDAQ"),
    CatalogEntry("AVGO", "Broadcom Inc.", "NASDAQ"),
)


_lock = threading.Lock()
_catalog: tuple[CatalogEntry, ...] = _FALLBACK_CATALOG
_loaded_at: float = 0.0  # monotonic seconds; 0 means "never refreshed"


def _trading_client() -> TradingClient:
    """Local copy of the Alpaca client constructor to avoid an
    import cycle with services.alpaca_client."""
    return TradingClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_api_secret,
        paper=settings.alpaca_paper,
    )


def refresh() -> int:
    """Fetch the assets list and replace the in-memory catalog.

    Returns the number of entries after refresh. Safe to call from
    APScheduler — failures are logged, never raised, and the prior
    catalog is preserved.
    """
    global _catalog, _loaded_at
    try:
        client = _trading_client()
        request = GetAssetsRequest(
            status=AssetStatus.ACTIVE,
            asset_class=AssetClass.US_EQUITY,
        )
        assets = client.get_all_assets(request)
    except Exception as exc:  # noqa: BLE001
        log.warning("symbol_catalog: refresh failed (%s); keeping prior catalog", exc)
        return len(_catalog)

    new_entries: list[CatalogEntry] = []
    for a in assets:
        if not getattr(a, "tradable", True):
            continue
        if getattr(a, "status", None) is not None and a.status != AssetStatus.ACTIVE:
            continue
        symbol = (getattr(a, "symbol", "") or "").strip().upper()
        if not symbol:
            continue
        if symbol in _INDEX_DENYLIST:
            continue
        name = (getattr(a, "name", "") or "").strip() or symbol
        exchange = (getattr(a, "exchange", "") or "").strip() or "—"
        new_entries.append(CatalogEntry(symbol, name, exchange))

    if not new_entries:
        log.warning(
            "symbol_catalog: refresh returned 0 entries; keeping prior catalog"
        )
        return len(_catalog)

    # Sort by symbol so ties break alphabetically without extra work in
    # the search path; also gives a deterministic test artifact.
    new_entries.sort(key=lambda e: e.symbol)
    with _lock:
        _catalog = tuple(new_entries)
        _loaded_at = time.monotonic()
    log.info("symbol_catalog: refreshed; %d entries", len(_catalog))
    return len(_catalog)


def search(q: str, limit: int = 10) -> list[CatalogEntry]:
    """Ranked substring search over the in-memory catalog. The scoring
    matches the router's prior behavior so a swap to this service
    doesn't change the existing test fixtures.
    """
    needle = q.strip().lower()
    if not needle:
        return []
    with _lock:
        snapshot = _catalog

    scored: list[tuple[float, CatalogEntry]] = []
    for entry in snapshot:
        if entry.symbol in _INDEX_DENYLIST:
            continue
        sym_lc = entry.symbol.lower()
        name_lc = entry.name.lower()
        score = 0.0
        if sym_lc == needle:
            score = 3.0
        elif sym_lc.startswith(needle):
            score = 2.0
        elif needle in sym_lc:
            score = 1.0
        elif needle in name_lc:
            score = 0.5
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: (-x[0], x[1].symbol))
    return [e for _, e in scored[:limit]]


def get_all() -> tuple[CatalogEntry, ...]:
    """Snapshot of the catalog. Used by tests + diagnostics."""
    with _lock:
        return _catalog


def is_loaded_from_alpaca() -> bool:
    """True iff `refresh()` has populated the catalog at least once
    in this process. Used by tests + diagnostic endpoints to
    distinguish a fresh boot (fallback list) from a warm cache."""
    return _loaded_at > 0
