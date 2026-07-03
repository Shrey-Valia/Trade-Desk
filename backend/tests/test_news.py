"""News feed — service parsing (mocked SDK) + the /api/news router contract.

The Alpaca news SDK is never hit: `_news_client` is monkeypatched to a fake
that returns canned articles (or raises), so these tests are deterministic
and offline.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import services.alpaca_client as ac
from services.alpaca_client import NewsUnavailable, get_news
from services.resilience import reset_breakers


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    # Fresh cache + breaker around each case so a negative-cache or open
    # breaker from one test can't bleed into the next.
    ac.cache._store.clear()  # type: ignore[attr-defined]
    reset_breakers()
    # Never sleep on the token bucket in tests.
    monkeypatch.setattr(ac._interactive_bucket, "take", lambda *a, **k: 0.0)
    monkeypatch.setattr(ac._background_bucket, "take", lambda *a, **k: 0.0)
    yield
    ac.cache._store.clear()  # type: ignore[attr-defined]
    reset_breakers()


class _FakeArticle:
    def __init__(self, **kw):
        self.id = kw.get("id", 1)
        self.headline = kw.get("headline", "")
        self.summary = kw.get("summary", "")
        self.source = kw.get("source", "")
        self.url = kw.get("url", "")
        self.created_at = kw.get("created_at")


class _FakeResp:
    def __init__(self, articles):
        # Mirrors alpaca-py: resp.data is {"news": [...]}.
        self.data = {"news": articles}


class _FakeNewsClient:
    def __init__(self, articles=None, raise_exc=None):
        self._articles = articles or []
        self._raise = raise_exc

    def get_news(self, _req):
        if self._raise is not None:
            raise self._raise
        return _FakeResp(self._articles)


def test_get_news_trims_and_shapes_articles(monkeypatch):
    created = datetime(2026, 6, 24, 14, 30, tzinfo=timezone.utc)
    art = _FakeArticle(
        id=42,
        headline="SPY rips on CPI print",
        summary="Cooler inflation lifts equities.",
        source="Benzinga",
        url="https://example.com/a",
        created_at=created,
    )
    monkeypatch.setattr(ac, "_news_client", lambda: _FakeNewsClient([art]))

    items = get_news("spy", limit=5)
    assert len(items) == 1
    it = items[0]
    assert it == {
        "id": "42",
        "headline": "SPY rips on CPI print",
        "summary": "Cooler inflation lifts equities.",
        "source": "Benzinga",
        "url": "https://example.com/a",
        "created_at": created.isoformat(),
    }


def test_get_news_empty_is_success_not_error(monkeypatch):
    monkeypatch.setattr(ac, "_news_client", lambda: _FakeNewsClient([]))
    assert get_news("NVDA") == []  # empty list, NOT NewsUnavailable


def test_get_news_raises_news_unavailable_on_failure(monkeypatch):
    monkeypatch.setattr(
        ac, "_news_client", lambda: _FakeNewsClient(raise_exc=RuntimeError("429 too many requests"))
    )
    with pytest.raises(NewsUnavailable):
        get_news("AAPL")
    # Negative-cached → a second call short-circuits to NewsUnavailable too.
    with pytest.raises(NewsUnavailable):
        get_news("AAPL")


def test_get_news_is_cached(monkeypatch):
    calls = {"n": 0}

    class _Counting(_FakeNewsClient):
        def get_news(self, _req):
            calls["n"] += 1
            return _FakeResp([])

    monkeypatch.setattr(ac, "_news_client", lambda: _Counting())
    get_news("MSFT")
    get_news("MSFT")
    assert calls["n"] == 1  # second read served from the 5-min cache


# -- router contract ---------------------------------------------------------


def test_news_endpoint_returns_items(api_client, monkeypatch):
    import routers.news as news_router

    monkeypatch.setattr(
        news_router,
        "get_news",
        lambda sym, limit: [
            {
                "id": "1",
                "headline": f"{sym} headline",
                "summary": "",
                "source": "wire",
                "url": "https://x",
                "created_at": "2026-06-24T00:00:00+00:00",
            }
        ],
    )
    res = api_client.get("/api/news?symbol=spy&limit=10")
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "SPY"
    assert body["items"][0]["headline"] == "SPY headline"


def test_news_endpoint_503_when_unavailable(api_client, monkeypatch):
    import routers.news as news_router

    def _boom(sym, limit):
        raise NewsUnavailable(sym)

    monkeypatch.setattr(news_router, "get_news", _boom)
    res = api_client.get("/api/news?symbol=SPY")
    assert res.status_code == 503
    assert res.json()["detail"] == "News unavailable"
