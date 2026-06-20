"""Symbol catalog — ranking + index-denylist defense.

The curated-universe rework swapped the live Alpaca asset catalog out
for a 30-symbol hand-curated list. These tests cover the search-path
adapter (services/symbol_catalog) that the existing ticker_search
router consumes. Curated-universe content/shape is covered separately
in test_curated_universe.py.
"""

from __future__ import annotations

from unittest.mock import patch

from services import curated_universe, symbol_catalog
from services.symbol_catalog import CatalogEntry


def test_get_all_returns_curated_entries():
    entries = symbol_catalog.get_all()
    syms = {e.symbol for e in entries}
    # Curated universe shape is enforced in test_curated_universe; here
    # we just confirm the catalog adapter passes them through.
    assert "SPY" in syms
    assert "AAPL" in syms
    assert "NVDA" in syms
    # Indices must not appear even if a future drift adds one.
    assert "SPX" not in syms
    assert "VIX" not in syms


def test_search_empty_query_returns_empty():
    assert symbol_catalog.search("") == []
    assert symbol_catalog.search("   ") == []


def test_search_exact_symbol_match_ranks_first():
    hits = symbol_catalog.search("SPY", limit=5)
    assert hits[0].symbol == "SPY"


def test_search_symbol_prefix_match():
    hits = symbol_catalog.search("AA", limit=10)
    syms = [h.symbol for h in hits]
    assert "AAPL" in syms


def test_search_substring_match():
    # "PY" is inside "SPY" — substring match (score 1.0).
    hits = symbol_catalog.search("PY", limit=10)
    syms = [h.symbol for h in hits]
    assert "SPY" in syms


def test_search_name_substring_match():
    hits = symbol_catalog.search("apple", limit=10)
    syms = [h.symbol for h in hits]
    assert "AAPL" in syms


def test_search_limit_caps_result_count():
    # "A" appears in many curated names/symbols; cap to 3 results.
    hits = symbol_catalog.search("A", limit=3)
    assert len(hits) <= 3


def test_search_ranking_order():
    # Exact > prefix > substring > name. Patch a tiny fixed catalog
    # into curated_universe to exercise the scoring path with
    # values we control.
    fixture = (
        curated_universe.CuratedEntry("AAA", "Aaa Holdings", "equity"),
        curated_universe.CuratedEntry("AAPL", "Apple Inc.", "equity"),
        curated_universe.CuratedEntry("PRAA", "PRA Group Inc.", "equity"),
        curated_universe.CuratedEntry("XYZ", "Acme AA Corp.", "equity"),
    )
    with patch.object(curated_universe, "CURATED_UNIVERSE", fixture):
        hits = symbol_catalog.search("AA", limit=10)
        syms = [h.symbol for h in hits]
        # AAA / AAPL both start with AA → score 2.0; alphabetical:
        # AAA before AAPL. PRAA contains AA → score 1.0. XYZ has
        # "AA" in name → score 0.5.
        assert syms == ["AAA", "AAPL", "PRAA", "XYZ"]


def test_search_filters_out_index_tickers():
    # Even if an index symbol leaks into the curated universe, the
    # denylist must catch it before it reaches the response.
    fixture = (
        curated_universe.CuratedEntry("SPX", "S&P 500 Index", "etf"),
        curated_universe.CuratedEntry("SPXL", "Direxion S&P 500 Bull 3X", "etf"),
        curated_universe.CuratedEntry("SPY", "SPDR S&P 500 ETF", "etf"),
        curated_universe.CuratedEntry("VIX", "CBOE Volatility Index", "etf"),
        curated_universe.CuratedEntry("VIXY", "ProShares VIX ETF", "etf"),
    )
    with patch.object(curated_universe, "CURATED_UNIVERSE", fixture):
        for needle in ("SPX", "NDX", "VIX", "RUT", "DJX", "OEX"):
            syms = [h.symbol for h in symbol_catalog.search(needle, limit=10)]
            assert needle not in syms, f"index {needle} leaked into search"
        # Adjacent equity tickers that share the substring still surface.
        assert "SPXL" in [h.symbol for h in symbol_catalog.search("SPX", limit=10)]
        assert "VIXY" in [h.symbol for h in symbol_catalog.search("VIX", limit=10)]
        assert "SPY" in [h.symbol for h in symbol_catalog.search("SPY", limit=10)]


def test_catalog_entry_shape_is_preserved():
    # The router builds SearchHit from these fields; if the dataclass
    # signature drifts the response will break.
    entries = symbol_catalog.get_all()
    sample: CatalogEntry = entries[0]
    assert isinstance(sample.symbol, str)
    assert isinstance(sample.name, str)
    assert isinstance(sample.exchange, str)
