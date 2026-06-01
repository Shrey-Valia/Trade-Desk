"""Ticker search — partial-match scoring + 0DTE-availability flag.

The catalog test cases are deterministic against the in-process
symbol_catalog fallback list. The 0DTE-flag cases monkeypatch
chain_availability.has_zero_dte_bulk so the test suite stays
hermetic — the real Alpaca contract-list call lives in
test_chain_availability.py with mocks of its own.
"""

from __future__ import annotations

from typing import Iterable

import pytest
from fastapi.testclient import TestClient

from main import app
from routers import ticker_search

client = TestClient(app)


@pytest.fixture(autouse=True)
def _stub_zero_dte_bulk(monkeypatch: pytest.MonkeyPatch):
    """Default stub: SPY/QQQ/IWM = True, everything else = False.
    Tests that need different behavior re-monkeypatch.
    """
    UNIVERSE = {"SPY", "QQQ", "IWM"}

    def stub(symbols: Iterable[str]) -> dict[str, bool]:
        return {s: (s in UNIVERSE) for s in symbols}

    monkeypatch.setattr(ticker_search, "has_zero_dte_bulk", stub)


def test_empty_query_returns_empty():
    r = client.get("/api/ticker/search?q=")
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == ""
    assert body["results"] == []


def test_exact_symbol_match_ranks_first():
    r = client.get("/api/ticker/search?q=SPY")
    assert r.status_code == 200
    body = r.json()
    assert body["results"][0]["symbol"] == "SPY"


def test_symbol_prefix_match():
    r = client.get("/api/ticker/search?q=AA")
    assert r.status_code == 200
    syms = [hit["symbol"] for hit in r.json()["results"]]
    assert "AAPL" in syms


def test_zero_dte_flag_is_dynamic_from_chain_check(monkeypatch: pytest.MonkeyPatch):
    """Phase 2: the flag now reflects what the chain-availability stub
    returns, not the static settings.zero_dte_universe."""
    monkeypatch.setattr(
        ticker_search,
        "has_zero_dte_bulk",
        lambda syms: {s: (s == "AAPL") for s in syms},  # only AAPL True
    )
    r = client.get("/api/ticker/search?q=AAPL")
    hit = next(h for h in r.json()["results"] if h["symbol"] == "AAPL")
    assert hit["has_0dte_today"] is True

    r2 = client.get("/api/ticker/search?q=SPY")
    hit2 = next(h for h in r2.json()["results"] if h["symbol"] == "SPY")
    assert hit2["has_0dte_today"] is False  # stub returned False for SPY


def test_default_stub_flags_spy_qqq_iwm():
    """Fixture default mirrors the prior universe so we keep a
    test that exercises the SPY/QQQ/IWM-as-true case."""
    r = client.get("/api/ticker/search?q=Q")
    by_sym = {h["symbol"]: h for h in r.json()["results"]}
    assert by_sym["QQQ"]["has_0dte_today"] is True


def test_non_zero_dte_match_has_no_badge():
    """AAPL is not in the default stub's True set → no badge."""
    r = client.get("/api/ticker/search?q=AAPL")
    hit = next(h for h in r.json()["results"] if h["symbol"] == "AAPL")
    assert hit["has_0dte_today"] is False


def test_name_substring_match():
    r = client.get("/api/ticker/search?q=apple")
    body = r.json()
    syms = [hit["symbol"] for hit in body["results"]]
    assert "AAPL" in syms


def test_limit_caps_result_count():
    r = client.get("/api/ticker/search?q=s&limit=3")
    assert r.status_code == 200
    assert len(r.json()["results"]) <= 3


def test_router_calls_zero_dte_bulk_once_per_query(monkeypatch: pytest.MonkeyPatch):
    """The router must batch the chain-availability check into a
    single bulk call per search — not one call per symbol via
    iteration. Catches a regression that would N+1 the search."""
    calls: list[list[str]] = []

    def spy(symbols):
        calls.append(list(symbols))
        return {s: False for s in symbols}

    monkeypatch.setattr(ticker_search, "has_zero_dte_bulk", spy)
    r = client.get("/api/ticker/search?q=SPY")
    assert r.status_code == 200
    assert len(calls) == 1
    # And the bulk call received the matching symbols, not a
    # single-symbol slice or an empty list.
    assert len(calls[0]) >= 1
