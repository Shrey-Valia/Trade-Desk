"""Router tests for routers/calendar.py — GET /api/calendar.

The 7-trading-day strip mixes earnings (Finnhub), economic releases
(FRED), and computed/static events. The external pulls (earnings_calendar,
releases_dates) are monkeypatched so the test is deterministic and
offline; the trading-day grid comes from the local pandas calendar.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import routers.calendar as cal
from config import settings
from services.cache import cache

_ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Reset the 1h calendar cache and stub the external pulls to empty by
    default so each test starts from a clean, offline baseline."""
    cache._store.clear()
    monkeypatch.setattr(cal, "earnings_calendar", lambda days_forward=30: [])
    monkeypatch.setattr(cal, "releases_dates", lambda start, end: [])
    yield
    cache._store.clear()


def _sessions() -> list[date]:
    today = datetime.now(_ET).date()
    return cal.next_trading_days(today, cal._DAYS)


def test_calendar_base_shape(api_client):
    res = api_client.get("/api/calendar")
    assert res.status_code == 200, res.text
    body = res.json()
    days = body["days"]
    assert len(days) == cal._DAYS
    # Exactly the next N trading-day ISO dates, in order.
    assert [d["date"] for d in days] == [s.isoformat() for s in _sessions()]
    # Each day carries an events list (possibly empty) + an is_today flag.
    for d in days:
        assert isinstance(d["events"], list)
        assert isinstance(d["is_today"], bool)
    # Exactly one day flagged today (today is always the first session).
    assert sum(1 for d in days if d["is_today"]) == 1


def test_calendar_injects_earnings_for_universe_symbol(api_client, monkeypatch):
    sessions = _sessions()
    target = sessions[1]  # any in-window trading day
    universe_symbol = sorted(settings.watchlist_universe)[0]

    def _earnings(days_forward=30):
        return [
            SimpleNamespace(symbol=universe_symbol, date=target.isoformat(), hour="bmo"),
            # Out-of-universe symbol must be filtered out.
            SimpleNamespace(symbol="ZZZNOTREAL", date=target.isoformat(), hour="amc"),
        ]

    monkeypatch.setattr(cal, "earnings_calendar", _earnings)

    body = api_client.get("/api/calendar").json()
    day = next(d for d in body["days"] if d["date"] == target.isoformat())
    earnings = [e for e in day["events"] if e["type"] == "earnings"]
    assert len(earnings) == 1
    assert earnings[0]["ticker"] == universe_symbol
    assert "BMO" in earnings[0]["title"]


def test_calendar_survives_earnings_provider_failure(api_client, monkeypatch):
    """A Finnhub blowup must not 500 the whole strip — earnings are skipped."""

    def _boom(days_forward=30):
        raise RuntimeError("finnhub down")

    monkeypatch.setattr(cal, "earnings_calendar", _boom)
    res = api_client.get("/api/calendar")
    assert res.status_code == 200, res.text
    assert len(res.json()["days"]) == cal._DAYS


def test_calendar_injects_fred_economic_release(api_client, monkeypatch):
    sessions = _sessions()
    target = sessions[2]
    # Use a canonical FRED release name the router maps to an event.
    canonical_name = cal.FRED_RELEASE_NAMES[0][0]

    monkeypatch.setattr(
        cal,
        "releases_dates",
        lambda start, end: [SimpleNamespace(date=target, release_name=canonical_name)],
    )
    body = api_client.get("/api/calendar").json()
    day = next(d for d in body["days"] if d["date"] == target.isoformat())
    assert any(e["type"] == "economic" for e in day["events"])


def test_calendar_is_cached(api_client, monkeypatch):
    calls = {"n": 0}

    def _earnings(days_forward=30):
        calls["n"] += 1
        return []

    monkeypatch.setattr(cal, "earnings_calendar", _earnings)
    api_client.get("/api/calendar")
    api_client.get("/api/calendar")
    assert calls["n"] == 1  # second hit served from the 1h cache
