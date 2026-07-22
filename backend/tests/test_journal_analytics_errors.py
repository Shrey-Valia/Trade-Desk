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

from models.trade import Trade
from tests.conftest import make_combine


@pytest.fixture
def client_and_session(auth_client, session_factory, monkeypatch):
    # Keep the endpoint offline: quote fetch falls back to the entry
    # price, rate falls back to the hardcoded default.
    import routers.journal as journal_router

    def _no_quotes(_symbols):
        raise RuntimeError("offline test")

    def _no_rate():
        raise RuntimeError("offline test")

    monkeypatch.setattr(journal_router, "get_quotes", _no_quotes)
    monkeypatch.setattr(journal_router, "latest_dgs3mo_rate", _no_rate)

    make_combine(auth_client, "50K")
    return auth_client, session_factory


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


def test_intraday_pop_computed_from_here(client_and_session):
    """POP on an open position (audit wave 7): the intraday engine reports
    the probability the position ends profitable at expiry from the current
    spot/clock. Driven directly (tomorrow's expiry → time strictly > 0 at
    any wall-clock hour) so the assertion is deterministic."""
    from datetime import datetime, timezone

    from routers.journal import _intraday_analytics

    t = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=110.0,
        is_paper=True,
        tier="50K",
        status="open",
    )
    t.id = 999_001  # unsaved row — analytics only echoes the id
    t.legs = [{
        "side": "call", "action": "buy", "strike": 100.0,
        "expiry": (date.today() + timedelta(days=1)).isoformat(),
        "contracts": 1, "entry_price": 1.1,
    }]
    out = _intraday_analytics(trade=t, spot=100.0, rate=0.045, elapsed_hours=0.0)
    assert out.pop is not None
    # ATM long call needs a move past BE ≈ 101.1 → strictly under a coin flip,
    # but with a day on the clock comfortably above zero.
    assert 0.0 < out.pop < 0.5
