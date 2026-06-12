"""Analytics endpoint vs corrupt stored legs — must 422, never 500.

A row whose legs_json is unparseable (or parseable but missing fields)
is a stored-data fault: the API should tell the client what's wrong
with that trade, not crash with a generic 500. These tests corrupt the
row directly in the DB, the only way this state can occur (the create
endpoint validates legs at the boundary).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from models.trade import Trade


@pytest.fixture
def client_and_session(monkeypatch):
    import models.trade  # noqa: F401 — registers Trade on Base.metadata

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    # Keep the endpoint offline: quote fetch falls back to the entry
    # price, rate falls back to the hardcoded default.
    import routers.journal as journal_router

    def _no_quotes(_symbols):
        raise RuntimeError("offline test")

    def _no_rate():
        raise RuntimeError("offline test")

    monkeypatch.setattr(journal_router, "get_quotes", _no_quotes)
    monkeypatch.setattr(journal_router, "latest_dgs3mo_rate", _no_rate)

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), TestingSession
    finally:
        app.dependency_overrides.pop(get_session, None)


def _multiday_payload():
    expiry = (date.today() + timedelta(days=30)).isoformat()
    return {
        "symbol": "AAPL",
        "strategy": "long_call",
        "legs": [
            {
                "side": "call",
                "action": "buy",
                "strike": 220.0,
                "expiry": expiry,
                "contracts": 1,
                "entry_price": 5.0,
            }
        ],
        "entry_date": "2026-06-01T14:30:00Z",
        "entry_underlying_price": 218.0,
        "is_paper": True,
    }


def _corrupt(TestingSession, trade_id: int, legs_json: str) -> None:
    with TestingSession() as s:
        trade = s.get(Trade, trade_id)
        trade.legs_json = legs_json
        s.commit()


def test_unparseable_legs_json_is_422(client_and_session):
    client, TestingSession = client_and_session
    tid = client.post("/api/journal/trades", json=_multiday_payload()).json()["id"]
    _corrupt(TestingSession, tid, "{not json")

    res = client.get(f"/api/journal/trades/{tid}/analytics")
    assert res.status_code == 422
    assert "legs" in res.json()["detail"]


def test_empty_legs_list_is_422(client_and_session):
    client, TestingSession = client_and_session
    tid = client.post("/api/journal/trades", json=_multiday_payload()).json()["id"]
    _corrupt(TestingSession, tid, "[]")

    res = client.get(f"/api/journal/trades/{tid}/analytics")
    assert res.status_code == 422


def test_legs_missing_fields_is_422(client_and_session):
    client, TestingSession = client_and_session
    tid = client.post("/api/journal/trades", json=_multiday_payload()).json()["id"]
    _corrupt(TestingSession, tid, '[{"side": "call"}]')

    res = client.get(f"/api/journal/trades/{tid}/analytics")
    assert res.status_code == 422


def test_healthy_trade_still_computes(client_and_session):
    client, _ = client_and_session
    tid = client.post("/api/journal/trades", json=_multiday_payload()).json()["id"]

    res = client.get(f"/api/journal/trades/{tid}/analytics")
    assert res.status_code == 200
    body = res.json()
    assert body["trade_id"] == tid
    # Quote fetch is monkeypatched offline — spot falls back to entry.
    assert body["spot"] == pytest.approx(218.0)
