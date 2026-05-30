"""Ticker search — partial-match scoring + 0DTE-availability flag."""

from __future__ import annotations

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


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


def test_zero_dte_universe_is_flagged():
    """SPY/QQQ/IWM are the 0DTE-eligible set; everything else is not."""
    r = client.get("/api/ticker/search?q=Q")
    assert r.status_code == 200
    by_sym = {hit["symbol"]: hit for hit in r.json()["results"]}
    assert by_sym["QQQ"]["has_0dte_today"] is True


def test_non_universe_match_has_no_0dte_badge():
    r = client.get("/api/ticker/search?q=AAPL")
    assert r.status_code == 200
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
