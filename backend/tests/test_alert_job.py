"""Server-side alert evaluation job — alerts fire with no tab open."""

from __future__ import annotations

import types

from sqlalchemy import select

from jobs.evaluate_alerts import evaluate_alerts
from models.alert import Alert
from models.notification import Notification


def _mk_alert(auth_client, threshold=100.0, direction="above", symbol="SPY"):
    res = auth_client.post(
        "/api/alerts",
        json={
            "kind": "price",
            "symbol": symbol,
            "threshold": threshold,
            "direction": direction,
            "note": "test",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _quotes(price):
    return lambda syms: {s: types.SimpleNamespace(price=price) for s in syms}


def test_trip_persists_and_notifies(auth_client, session_factory):
    aid = _mk_alert(auth_client, threshold=100.0, direction="above")
    out = evaluate_alerts(session_factory, quotes_for=_quotes(105.0))
    assert out == {"evaluated": 1, "triggered": 1}
    s = session_factory()
    alert = s.get(Alert, aid)
    assert alert.status == "triggered" and alert.triggered_at is not None
    notes = s.execute(
        select(Notification).where(Notification.kind == "price_alert")
    ).scalars().all()
    assert len(notes) == 1
    assert "SPY" in notes[0].title
    s.close()


def test_not_crossed_stays_active(auth_client, session_factory):
    aid = _mk_alert(auth_client, threshold=100.0, direction="above")
    out = evaluate_alerts(session_factory, quotes_for=_quotes(95.0))
    assert out == {"evaluated": 1, "triggered": 0}
    s = session_factory()
    assert s.get(Alert, aid).status == "active"
    s.close()


def test_zero_price_never_trips_below(auth_client, session_factory):
    aid = _mk_alert(auth_client, threshold=100.0, direction="below")
    out = evaluate_alerts(session_factory, quotes_for=_quotes(0.0))
    assert out["triggered"] == 0
    s = session_factory()
    assert s.get(Alert, aid).status == "active"
    s.close()


def test_idempotent_no_refire(auth_client, session_factory):
    _mk_alert(auth_client, threshold=100.0, direction="above")
    evaluate_alerts(session_factory, quotes_for=_quotes(105.0))
    out = evaluate_alerts(session_factory, quotes_for=_quotes(110.0))
    assert out == {"evaluated": 0, "triggered": 0}


def test_feed_failure_leaves_alerts_armed(auth_client, session_factory):
    aid = _mk_alert(auth_client, threshold=100.0, direction="above")

    def _boom(_syms):
        raise RuntimeError("feed down")

    out = evaluate_alerts(session_factory, quotes_for=_boom)
    assert out["triggered"] == 0
    s = session_factory()
    assert s.get(Alert, aid).status == "active"
    s.close()
