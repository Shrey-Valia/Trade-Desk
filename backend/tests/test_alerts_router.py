"""Alerts router — CRUD, per-user isolation, and price evaluation (WS6)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from routers.alerts import price_alert_tripped


# ---------------------------------------------------------------------------
# Pure trigger logic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "direction,threshold,price,expected",
    [
        ("above", 100.0, 101.0, True),
        ("above", 100.0, 100.0, True),  # inclusive at the line
        ("above", 100.0, 99.5, False),
        ("below", 100.0, 99.0, True),
        ("below", 100.0, 100.0, True),
        ("below", 100.0, 100.5, False),
        (None, 100.0, 999.0, False),  # malformed never trips
        ("above", None, 999.0, False),
    ],
)
def test_price_alert_tripped(direction, threshold, price, expected):
    assert price_alert_tripped(direction, threshold, price) is expected


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_alerts_empty_on_fresh_user(auth_client):
    r = auth_client.get("/api/alerts")
    assert r.status_code == 200
    assert r.json() == {"alerts": []}


def test_create_price_alert(auth_client):
    r = auth_client.post(
        "/api/alerts",
        json={
            "kind": "price",
            "symbol": "spy",
            "threshold": 510.0,
            "direction": "above",
            "note": "breakout",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["symbol"] == "SPY"  # normalized upper
    assert body["kind"] == "price"
    assert body["status"] == "active"
    assert body["threshold"] == 510.0
    assert body["direction"] == "above"
    assert body["triggered_at"] is None


def test_price_alert_requires_threshold_and_direction(auth_client):
    assert auth_client.post(
        "/api/alerts", json={"kind": "price", "symbol": "SPY"}
    ).status_code == 400
    assert auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 100, "direction": "sideways"},
    ).status_code == 400
    assert auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": -5, "direction": "above"},
    ).status_code == 400


def test_create_rejects_bad_kind(auth_client):
    r = auth_client.post("/api/alerts", json={"kind": "moon", "symbol": "SPY"})
    assert r.status_code == 400


def test_earnings_alert_clears_price_fields(auth_client):
    r = auth_client.post(
        "/api/alerts",
        json={"kind": "earnings", "symbol": "AAPL", "threshold": 99, "direction": "above"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["threshold"] is None
    assert body["direction"] is None


def test_delete_alert(auth_client):
    aid = auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 1, "direction": "above"},
    ).json()["id"]
    assert auth_client.delete(f"/api/alerts/{aid}").status_code == 204
    assert auth_client.get("/api/alerts").json()["alerts"] == []


def test_delete_missing_alert_404(auth_client):
    assert auth_client.delete("/api/alerts/9999").status_code == 404


def test_rearm_resets_triggered_state(auth_client):
    aid = auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 1, "direction": "above"},
    ).json()["id"]
    # Trip it via evaluate (price 500 >= 1).
    with patch(
        "routers.alerts.get_quotes",
        return_value={"SPY": SimpleNamespace(price=500.0)},
    ):
        auth_client.post("/api/alerts/evaluate")
    listed = auth_client.get("/api/alerts").json()["alerts"]
    assert listed[0]["status"] == "triggered"
    # Re-arm.
    r = auth_client.post(f"/api/alerts/{aid}/rearm")
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    assert r.json()["triggered_at"] is None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def test_evaluate_trips_crossing_alert(auth_client):
    auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 500, "direction": "above"},
    )
    with patch(
        "routers.alerts.get_quotes",
        return_value={"SPY": SimpleNamespace(price=505.0)},
    ):
        r = auth_client.post("/api/alerts/evaluate")
    assert r.status_code == 200
    trig = r.json()["triggered"]
    assert len(trig) == 1
    assert trig[0]["symbol"] == "SPY"
    assert trig[0]["status"] == "triggered"
    # Second evaluate is idempotent — the alert is no longer active.
    with patch(
        "routers.alerts.get_quotes",
        return_value={"SPY": SimpleNamespace(price=505.0)},
    ):
        r2 = auth_client.post("/api/alerts/evaluate")
    assert r2.json()["triggered"] == []


def test_evaluate_does_not_trip_below_threshold(auth_client):
    auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 500, "direction": "above"},
    )
    with patch(
        "routers.alerts.get_quotes",
        return_value={"SPY": SimpleNamespace(price=499.0)},
    ):
        r = auth_client.post("/api/alerts/evaluate")
    assert r.json()["triggered"] == []
    assert auth_client.get("/api/alerts").json()["alerts"][0]["status"] == "active"


def test_evaluate_survives_quote_failure(auth_client):
    auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 500, "direction": "above"},
    )
    with patch("routers.alerts.get_quotes", side_effect=RuntimeError("alpaca down")):
        r = auth_client.post("/api/alerts/evaluate")
    assert r.status_code == 200
    assert r.json()["triggered"] == []


# ---------------------------------------------------------------------------
# Auth + isolation
# ---------------------------------------------------------------------------


def test_alerts_require_auth(api_client):
    assert api_client.get("/api/alerts").status_code == 401
    assert api_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 1, "direction": "above"},
    ).status_code == 401


def test_alerts_are_per_user(auth_client, second_user_client):
    auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 1, "direction": "above"},
    )
    # The rival sees none of the first user's alerts.
    assert second_user_client.get("/api/alerts").json()["alerts"] == []


def test_cannot_delete_another_users_alert(auth_client, second_user_client):
    aid = auth_client.post(
        "/api/alerts",
        json={"kind": "price", "symbol": "SPY", "threshold": 1, "direction": "above"},
    ).json()["id"]
    # Rival's delete is a 404 (existence not leaked); the owner still has it.
    assert second_user_client.delete(f"/api/alerts/{aid}").status_code == 404
    assert len(auth_client.get("/api/alerts").json()["alerts"]) == 1
