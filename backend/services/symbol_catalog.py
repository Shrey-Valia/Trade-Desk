"""Symbol catalog — thin adapter over the curated 0DTE universe.

Historical context: this module used to maintain a live ~13K-symbol
catalog refreshed daily from Alpaca's assets endpoint. The new search
modal (Phase 1 curated-universe rework) scopes search to the curated
30 names that actually have liquid 0DTE chains, so the live-asset
catalog is retired.

This module is kept around as a stable adapter so the existing
`routers/ticker_search.py` doesn't need to change shape — same
`CatalogEntry`, same `search()` ranking, same `_INDEX_DENYLIST`
defense. It just sources entries from `curated_universe` now.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from services import curated_universe

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CatalogEntry:
    symbol: str
    name: str
    exchange: str  # Retained for response-shape compatibility.


# Cash-settled CBOE indices are not equities — no Alpaca bars endpoint,
# no chain on the free tier (see commit f9bd590). The curated universe
# already excludes them, but this defense stays so any future drift
# (someone accidentally adds SPX to the curated list) is caught at the
# search layer too.
_INDEX_DENYLIST: frozenset[str] = frozenset(
    {"SPX", "NDX", "RUT", "VIX", "DJX", "OEX", "XSP", "XEO", "MXEF", "RUI"}
)


def _curated_to_catalog(e: curated_universe.CuratedEntry) -> CatalogEntry:
    # Exchange isn't tracked in the curated universe (we only need it
    # for the legacy response shape). "CURATED" is a clearer sentinel
    # than picking a real exchange we don't actually verify.
    return CatalogEntry(symbol=e.symbol, name=e.name, exchange="CURATED")


def search(q: str, limit: int = 10) -> list[CatalogEntry]:
    """Ranked substring search over the curated universe.

    Same scoring rubric as the live-Alpaca era so the response shape
    is unchanged from the search router's perspective:
        3.0  exact symbol match
        2.0  symbol-prefix match
        1.0  symbol-substring match
        0.5  name-substring match
    Denylisted indices are dropped even if a future caller injects them.
    """
    needle = q.strip().lower()
    if not needle:
        return []
    scored: list[tuple[float, CatalogEntry]] = []
    for e in curated_universe.CURATED_UNIVERSE:
        if e.symbol in _INDEX_DENYLIST:
            continue
        sym_lc = e.symbol.lower()
        name_lc = e.name.lower()
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
            scored.append((score, _curated_to_catalog(e)))
    scored.sort(key=lambda x: (-x[0], x[1].symbol))
    return [e for _, e in scored[:limit]]


def get_all() -> tuple[CatalogEntry, ...]:
    """Snapshot of the catalog — diagnostics and tests."""
    return tuple(
        _curated_to_catalog(e)
        for e in curated_universe.CURATED_UNIVERSE
        if e.symbol not in _INDEX_DENYLIST
    )
