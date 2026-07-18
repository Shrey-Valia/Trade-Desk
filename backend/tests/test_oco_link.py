"""OCO link/unlink endpoints — user-facing pairing of working orders.

The monitor already honors oco_group (one fill cancels the resting
siblings); these endpoints are the missing way to CREATE the pairing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from models.trade import Trade
from services.order_monitor import run_order_monitor
from tests.conftest import make_combine

_TODAY = datetime.now(UTC).date()


def _seed_working(session_factory, combine_id, limit_price=1.0, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(UTC),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
        status="working",
        order_type="limit",
        limit_price=limit_price,
    )
    defaults.update(kw)
    t = Trade(**defaults)
    t.legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _get(session_factory, tid):
    s = session_factory()
    t = s.get(Trade, tid)
    s.close()
    return t


def test_link_assigns_one_group(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    a = _seed_working(session_factory, c["id"])
    b = _seed_working(session_factory, c["id"])
    res = auth_client.post(
        "/api/journal/orders/oco-link", json={"trade_ids": [a, b]}
    )
    assert res.status_code == 200, res.text
    groups = {t["oco_group"] for t in res.json()["trades"]}
    assert len(groups) == 1 and None not in groups


def test_link_rejects_non_working(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    a = _seed_working(session_factory, c["id"])
    b = _seed_working(session_factory, c["id"], status="open", order_type="market")
    res = auth_client.post(
        "/api/journal/orders/oco-link", json={"trade_ids": [a, b]}
    )
    assert res.status_code == 409


def test_link_rejects_duplicates_and_short_lists(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    a = _seed_working(session_factory, c["id"])
    res = auth_client.post(
        "/api/journal/orders/oco-link", json={"trade_ids": [a, a]}
    )
    assert res.status_code == 422
    res = auth_client.post(
        "/api/journal/orders/oco-link", json={"trade_ids": [a]}
    )
    assert res.status_code == 422


def test_unlink_clears_group(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    a = _seed_working(session_factory, c["id"])
    b = _seed_working(session_factory, c["id"])
    auth_client.post("/api/journal/orders/oco-link", json={"trade_ids": [a, b]})
    res = auth_client.post(
        "/api/journal/orders/oco-unlink", json={"trade_ids": [a, b]}
    )
    assert res.status_code == 200
    assert all(t["oco_group"] is None for t in res.json()["trades"])


def test_linked_pair_one_fill_cancels_sibling(auth_client, session_factory):
    """End-to-end: link via the API, then a monitor fill on one cancels the
    other — the OCO guarantee the UI promises."""
    c = make_combine(auth_client, "50K")
    a = _seed_working(session_factory, c["id"], limit_price=1.0)
    b = _seed_working(session_factory, c["id"], limit_price=0.2)
    res = auth_client.post(
        "/api/journal/orders/oco-link", json={"trade_ids": [a, b]}
    )
    assert res.status_code == 200

    from datetime import time as dt_time

    summary = run_order_monitor(
        session_factory=session_factory,
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 0.9,  # fills a's limit 1.0; b's 0.2 stays away
        unrealized_for=lambda t, s: 0.0,
        now=datetime.combine(_TODAY, dt_time(17, 0), tzinfo=UTC),
    )
    assert summary["filled"] == 1
    assert _get(session_factory, a).status == "open"
    assert _get(session_factory, b).status == "cancelled"
