"""Symbol catalog — ranking + fallback behavior.

These tests exercise the in-memory catalog service without hitting
Alpaca's network. The fallback set ships in the module so the test
suite can validate scoring against a deterministic 16-symbol list
even before refresh() runs.
"""

from __future__ import annotations

from unittest.mock import patch

from services import symbol_catalog
from services.symbol_catalog import CatalogEntry, _FALLBACK_CATALOG


def test_fallback_catalog_is_loaded_at_import():
    # Fresh import → search must work against the bundled fallback
    # so the endpoint is never empty for a user querying SPY/QQQ/etc.
    entries = symbol_catalog.get_all()
    assert len(entries) >= len(_FALLBACK_CATALOG)
    syms = {e.symbol for e in entries}
    assert "SPY" in syms
    assert "AAPL" in syms


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
    hits = symbol_catalog.search("PY", limit=10)
    syms = [h.symbol for h in hits]
    assert "SPY" in syms  # symbol contains "PY"


def test_search_name_substring_match():
    hits = symbol_catalog.search("apple", limit=10)
    syms = [h.symbol for h in hits]
    assert "AAPL" in syms


def test_search_limit_caps_result_count():
    hits = symbol_catalog.search("S", limit=2)
    assert len(hits) <= 2


def test_search_ranking_order():
    # Exact > prefix > substring > name. Build a tiny fixed catalog
    # patched into the module to exercise the scoring path with
    # values we control.
    fixture = (
        CatalogEntry("AAA", "Aaa Holdings", "NYSE"),
        CatalogEntry("AAPL", "Apple Inc.", "NASDAQ"),
        CatalogEntry("PRAA", "PRA Group Inc.", "NASDAQ"),       # substring
        CatalogEntry("XYZ",  "Acme AA Corp.", "NYSE"),          # name substring
    )
    with patch.object(symbol_catalog, "_catalog", fixture):
        hits = symbol_catalog.search("AA", limit=10)
        syms = [h.symbol for h in hits]
        # AAA / AAPL both start with AA → score 2.0; alphabetical:
        # AAA before AAPL. PRAA contains AA → score 1.0. XYZ has
        # "AA" in name → score 0.5.
        assert syms == ["AAA", "AAPL", "PRAA", "XYZ"]


def test_refresh_returns_zero_keeps_prior_catalog():
    # Mock TradingClient.get_all_assets to return an empty list — the
    # service must NOT clobber the prior catalog.
    prior = symbol_catalog.get_all()
    prior_len = len(prior)

    class _StubClient:
        def get_all_assets(self, _req):
            return []

    with patch.object(symbol_catalog, "_trading_client", return_value=_StubClient()):
        returned = symbol_catalog.refresh()

    assert returned == prior_len
    assert symbol_catalog.get_all() == prior


def test_refresh_raises_keeps_prior_catalog():
    prior_len = len(symbol_catalog.get_all())

    class _RaisingClient:
        def get_all_assets(self, _req):
            raise RuntimeError("alpaca down")

    with patch.object(symbol_catalog, "_trading_client", return_value=_RaisingClient()):
        returned = symbol_catalog.refresh()

    assert returned == prior_len  # untouched


def test_refresh_populates_with_live_data():
    # Stub TradingClient.get_all_assets to return synthetic Asset-like
    # objects. The service should normalize, sort, and replace.
    class _Asset:
        def __init__(self, symbol, name, exchange, tradable=True):
            self.symbol = symbol
            self.name = name
            self.exchange = exchange
            self.tradable = tradable
            from alpaca.trading.enums import AssetStatus

            self.status = AssetStatus.ACTIVE

    class _StubClient:
        def get_all_assets(self, _req):
            return [
                _Asset("ZZZ", "Zeta Holdings", "NASDAQ"),
                _Asset("AAA", "Alpha Holdings", "NYSE"),
                _Asset("INACTIVE", "Should Skip", "NYSE", tradable=False),
            ]

    with patch.object(symbol_catalog, "_trading_client", return_value=_StubClient()):
        n = symbol_catalog.refresh()

    assert n == 2
    syms = [e.symbol for e in symbol_catalog.get_all()]
    assert syms == ["AAA", "ZZZ"]  # sorted
    assert "INACTIVE" not in syms
    assert symbol_catalog.is_loaded_from_alpaca()

    # Restore the fallback for downstream tests in this run.
    with patch.object(symbol_catalog, "_trading_client", return_value=_StubClient()):
        pass
    symbol_catalog._catalog = _FALLBACK_CATALOG  # noqa: SLF001 — test teardown


def test_search_filters_out_index_tickers():
    # SPX/NDX/VIX/RUT are cash-settled indices, not equities — the
    # chart/chain endpoints 404 on them. Even if Alpaca starts listing
    # one as us_equity (or a fallback row sneaks one in), search must
    # never surface them.
    fixture = (
        CatalogEntry("SPX", "S&P 500 Index", "INDEX"),
        CatalogEntry("SPXL", "Direxion Daily S&P 500 Bull 3X", "ARCA"),
        CatalogEntry("SPY", "SPDR S&P 500 ETF", "ARCA"),
        CatalogEntry("VIX", "CBOE Volatility Index", "INDEX"),
        CatalogEntry("VIXY", "ProShares VIX ST Futures ETF", "BATS"),
    )
    with patch.object(symbol_catalog, "_catalog", fixture):
        for needle in ("SPX", "NDX", "VIX", "RUT", "DJX", "OEX"):
            syms = [h.symbol for h in symbol_catalog.search(needle, limit=10)]
            assert needle not in syms, f"index {needle} leaked into search"
        # Adjacent equity tickers that happen to share the substring
        # must still come back.
        assert "SPXL" in [h.symbol for h in symbol_catalog.search("SPX", limit=10)]
        assert "VIXY" in [h.symbol for h in symbol_catalog.search("VIX", limit=10)]
        assert "SPY" in [h.symbol for h in symbol_catalog.search("SPY", limit=10)]


def test_refresh_drops_indices_from_alpaca_payload():
    # If Alpaca's us_equity list ever contains an index symbol (it has
    # happened historically — some delisted index proxies linger), the
    # refresh path must drop it before it lands in the catalog.
    class _Asset:
        def __init__(self, symbol, name, exchange, tradable=True):
            self.symbol = symbol
            self.name = name
            self.exchange = exchange
            self.tradable = tradable
            from alpaca.trading.enums import AssetStatus

            self.status = AssetStatus.ACTIVE

    class _StubClient:
        def get_all_assets(self, _req):
            return [
                _Asset("AAPL", "Apple Inc.", "NASDAQ"),
                _Asset("SPX", "S&P 500 Index", "INDEX"),
                _Asset("VIX", "CBOE Volatility Index", "INDEX"),
                _Asset("SPY", "SPDR S&P 500 ETF", "ARCA"),
            ]

    with patch.object(symbol_catalog, "_trading_client", return_value=_StubClient()):
        symbol_catalog.refresh()

    syms = {e.symbol for e in symbol_catalog.get_all()}
    assert "SPX" not in syms
    assert "VIX" not in syms
    assert "AAPL" in syms
    assert "SPY" in syms

    # Restore for downstream tests.
    symbol_catalog._catalog = _FALLBACK_CATALOG  # noqa: SLF001 — test teardown
