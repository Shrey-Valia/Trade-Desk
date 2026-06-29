"""Router tests for routers/watchlist.py — GET /api/watchlist.

The watchlist is DB-backed (watchlist_items), refreshed by a background
job. These tests seed rows directly (no network) and assert the bucketed
response shape, metadata parsing, and the free-tier sentiment notes.

The conftest db_engine fixture only imports a fixed model set, so we
import WatchlistItem here and ensure its table exists on the test engine
before seeding.
"""

from __future__ import annotations

import json

import pytest

from database import get_session
from models.watchlist_item import WatchlistItem


@pytest.fixture
def watchlist_db(api_client, db_engine):
    """Ensure the watchlist_items table exists on the in-memory test engine
    (the shared db_engine fixture doesn't import this model), then yield the
    authenticated-free client."""
    WatchlistItem.__table__.create(bind=db_engine, checkfirst=True)
    return api_client


def _seed(client, **kwargs) -> None:
    session = next(client.app.dependency_overrides[get_session]())
    session.add(WatchlistItem(**kwargs))
    session.commit()
    session.close()


def test_watchlist_empty_returns_all_buckets(watchlist_db):
    res = watchlist_db.get("/api/watchlist")
    assert res.status_code == 200, res.text
    body = res.json()
    for bucket in (
        "hot_now",
        "earnings",
        "unusual_options",
        "sentiment_up",
        "sentiment_down",
    ):
        assert body[bucket] == []
    assert "updated_at" in body


def test_watchlist_buckets_rows_by_category(watchlist_db):
    _seed(
        watchlist_db,
        category="hot_now",
        symbol="SPY",
        rank=0,
        price=500.0,
        change_pct=1.2,
        subtitle="vol spike",
        metadata_json=json.dumps({"news_count": 3}),
    )
    _seed(
        watchlist_db,
        category="earnings",
        symbol="AAPL",
        rank=0,
        price=210.0,
        change_pct=-0.5,
        subtitle="ER tomorrow",
        metadata_json=json.dumps({"earnings_date": "2026-07-01"}),
    )

    body = watchlist_db.get("/api/watchlist").json()
    assert [r["symbol"] for r in body["hot_now"]] == ["SPY"]
    assert body["hot_now"][0]["metadata"]["news_count"] == 3
    assert [r["symbol"] for r in body["earnings"]] == ["AAPL"]
    assert body["earnings"][0]["metadata"]["earnings_date"] == "2026-07-01"


def test_watchlist_unknown_category_is_ignored(watchlist_db):
    _seed(
        watchlist_db,
        category="not_a_real_bucket",
        symbol="XYZ",
        rank=0,
        price=1.0,
        change_pct=0.0,
        subtitle="",
        metadata_json="{}",
    )
    body = watchlist_db.get("/api/watchlist").json()
    # Row in an unknown category is dropped, not surfaced anywhere.
    for bucket in ("hot_now", "earnings", "unusual_options", "sentiment_up", "sentiment_down"):
        assert body[bucket] == []


def test_watchlist_bad_metadata_json_degrades_gracefully(watchlist_db):
    _seed(
        watchlist_db,
        category="hot_now",
        symbol="TSLA",
        rank=0,
        price=250.0,
        change_pct=2.0,
        subtitle="",
        metadata_json="{not valid json",  # malformed
    )
    body = watchlist_db.get("/api/watchlist").json()
    # Falls back to an empty metadata object rather than 500ing.
    assert body["hot_now"][0]["symbol"] == "TSLA"
    assert body["hot_now"][0]["metadata"]["news_count"] is None


def test_watchlist_notes_flag_sentiment_when_unavailable(watchlist_db, monkeypatch):
    """Free-tier Finnhub has no sentiment → the response carries a note on
    both sentiment buckets so the UI shows a reason, not a bare empty state."""
    import routers.watchlist as wl

    monkeypatch.setattr(wl, "SENTIMENT_AVAILABLE", False)
    monkeypatch.setattr(wl, "SENTIMENT_NOTE", "Sentiment unavailable on free tier")

    body = watchlist_db.get("/api/watchlist").json()
    assert body["notes"]["sentiment_up"] == "Sentiment unavailable on free tier"
    assert body["notes"]["sentiment_down"] == "Sentiment unavailable on free tier"


def test_watchlist_no_notes_when_sentiment_available(watchlist_db, monkeypatch):
    import routers.watchlist as wl

    monkeypatch.setattr(wl, "SENTIMENT_AVAILABLE", True)
    body = watchlist_db.get("/api/watchlist").json()
    assert "sentiment_up" not in body["notes"]
    assert "sentiment_down" not in body["notes"]
