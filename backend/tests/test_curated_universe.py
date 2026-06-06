"""Curated 0DTE-tradeable universe — shape + lookup helpers."""

from __future__ import annotations

from services import curated_universe


def test_universe_contains_exactly_30_symbols():
    assert len(curated_universe.CURATED_UNIVERSE) == 30


def test_universe_symbols_are_unique():
    syms = [e.symbol for e in curated_universe.CURATED_UNIVERSE]
    assert len(set(syms)) == len(syms)


def test_universe_categorization():
    by_cat = {e.symbol: e.category for e in curated_universe.CURATED_UNIVERSE}
    # Broad-market ETFs are tagged "etf"; single-name issues are "equity".
    assert by_cat["SPY"] == "etf"
    assert by_cat["QQQ"] == "etf"
    assert by_cat["IWM"] == "etf"
    assert by_cat["DIA"] == "etf"
    assert by_cat["AAPL"] == "equity"
    assert by_cat["NVDA"] == "equity"


def test_universe_excludes_indices():
    # Cash-settled CBOE indices have no Alpaca bars/chain on the free
    # tier — even though the search-layer denylist would catch them,
    # they must never appear in the curated source.
    syms = {e.symbol for e in curated_universe.CURATED_UNIVERSE}
    for index_sym in ("SPX", "NDX", "RUT", "VIX", "DJX", "OEX"):
        assert index_sym not in syms


def test_lookup_returns_entry_or_none():
    e = curated_universe.lookup("SPY")
    assert e is not None and e.symbol == "SPY" and e.category == "etf"
    assert curated_universe.lookup("spy").symbol == "SPY"  # case-insensitive
    assert curated_universe.lookup("ZZZZ") is None
    assert curated_universe.lookup("") is None


def test_is_in_universe():
    assert curated_universe.is_in_universe("SPY")
    assert curated_universe.is_in_universe("aapl")
    assert not curated_universe.is_in_universe("SPX")  # index, intentionally excluded
    assert not curated_universe.is_in_universe("ZZZZ")


def test_popular_is_subset_of_universe_and_has_eight_entries():
    pop = curated_universe.get_popular()
    assert len(pop) == 8
    universe_syms = {e.symbol for e in curated_universe.CURATED_UNIVERSE}
    for entry in pop:
        assert entry.symbol in universe_syms
