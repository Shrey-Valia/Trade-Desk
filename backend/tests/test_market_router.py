"""Router tests for routers/market.py — status / indices / universes.

External calls (get_market_clock, get_quotes, vix_history) are
monkeypatched on the `routers.market` module so nothing hits the network.
The Alpaca-clock path AND the local-calendar fallback are both exercised.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import routers.market as market
from config import settings
from services.alpaca_client import MarketClock, Quote
from services.cache import cache

_ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _clear_cache():
    """market.py caches status/indices for a few seconds. Reset the backing
    store around each test so a value from one test isn't served to the next."""
    cache._store.clear()
    yield
    cache._store.clear()


def _clock(is_open: bool) -> MarketClock:
    now = datetime.now(_ET)
    return MarketClock(
        is_open=is_open,
        timestamp=now,
        next_open=now + timedelta(hours=1),
        next_close=now + timedelta(hours=7),
    )


# -- /status -----------------------------------------------------------------


def test_status_open_from_alpaca_clock(api_client, monkeypatch):
    monkeypatch.setattr(market, "get_market_clock", lambda: _clock(is_open=True))
    res = api_client.get("/api/market/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "open"
    assert body["label"] == "Open"
    assert body["next_open"] is not None


def test_status_closed_from_alpaca_clock(api_client, monkeypatch):
    # Closed clock whose next_open is the same day → router derives a
    # pre/after/closed label from ET wall-clock; any of those is valid here.
    monkeypatch.setattr(market, "get_market_clock", lambda: _clock(is_open=False))
    res = api_client.get("/api/market/status")
    assert res.status_code == 200, res.text
    assert res.json()["status"] in {"closed", "pre", "after"}


def test_status_falls_back_to_local_calendar(api_client, monkeypatch):
    """Alpaca clock None → the pandas_market_calendars fallback runs and
    still returns a well-formed status (no 500)."""
    monkeypatch.setattr(market, "get_market_clock", lambda: None)
    res = api_client.get("/api/market/status")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] in {"open", "closed", "pre", "after"}
    assert isinstance(body["label"], str) and body["label"]


def test_status_is_cached(api_client, monkeypatch):
    """Second call inside the 15s TTL doesn't re-hit the clock."""
    calls = {"n": 0}

    def _counting_clock():
        calls["n"] += 1
        return _clock(is_open=True)

    monkeypatch.setattr(market, "get_market_clock", _counting_clock)
    api_client.get("/api/market/status")
    api_client.get("/api/market/status")
    assert calls["n"] == 1


# -- /indices ----------------------------------------------------------------


def _q(symbol: str, price: float) -> Quote:
    return Quote(symbol=symbol, price=price, prev_close=price - 1.0)


def test_indices_success_shape(api_client, monkeypatch):
    monkeypatch.setattr(
        market,
        "get_quotes",
        lambda syms: {"SPY": _q("SPY", 500.0), "QQQ": _q("QQQ", 400.0)},
    )
    # VIX comes from FRED: a 2-point series → change_pct computed.
    monkeypatch.setattr(
        market,
        "vix_history",
        lambda start, end: {
            datetime(2026, 6, 24).date(): 14.0,
            datetime(2026, 6, 25).date(): 15.0,
        },
    )

    res = api_client.get("/api/market/indices")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["spy"]["symbol"] == "SPY" and body["spy"]["price"] == 500.0
    assert body["qqq"]["price"] == 400.0
    assert body["vix"]["symbol"] == "VIX" and body["vix"]["price"] == 15.0
    # change_pct = (15-14)/14*100
    assert body["vix"]["change_pct"] == pytest.approx((1 / 14) * 100)


def test_indices_handles_missing_quotes_and_vix(api_client, monkeypatch):
    monkeypatch.setattr(market, "get_quotes", lambda syms: {})  # no SPY/QQQ
    monkeypatch.setattr(market, "vix_history", lambda start, end: {})  # no VIX
    res = api_client.get("/api/market/indices")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["spy"] is None and body["qqq"] is None and body["vix"] is None


# -- universes ---------------------------------------------------------------


def test_liquid_universe_mirrors_settings(api_client):
    res = api_client.get("/api/market/liquid_universe")
    assert res.status_code == 200, res.text
    assert res.json()["symbols"] == list(settings.prewarm_liquid_universe)


def test_zerodte_universe_mirrors_settings(api_client):
    res = api_client.get("/api/market/zerodte_universe")
    assert res.status_code == 200, res.text
    assert res.json()["symbols"] == list(settings.zero_dte_universe)
