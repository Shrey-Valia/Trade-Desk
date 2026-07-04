"""Order modification (cancel/replace) — PATCH /api/journal/trades/{id}/order.

Working-only (409 otherwise), placement-grade validation (positive prices,
stop_price only while the order rests as a stop_limit), single-leg display
placeholder + net kept in sync with the new limit, and the copy-trade
cascade via mirror_modify (still-working follower copies only).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from models.combine import Combine
from models.trade import Trade
from services.copy_trade import mirror_open
from tests.conftest import make_combine

_TODAY = datetime.now(timezone.utc).date()


def _seed(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=100.0,
        status="working",
        order_type="limit",
        limit_price=1.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
    )
    defaults.update(kw)
    legs = defaults.pop("_legs", None)
    t = Trade(**defaults)
    t.legs = legs or [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _get(session_factory, tid) -> Trade:
    s = session_factory()
    t = s.get(Trade, tid)
    s.expunge(t)
    s.close()
    return t


def test_modify_limit_price_updates_order_and_placeholder(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    res = auth_client.patch(
        f"/api/journal/trades/{tid}/order", json={"limit_price": 2.5}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "working"
    assert body["limit_price"] == 2.5
    # Single-leg display placeholder + net follow the new trigger.
    assert body["legs"][0]["entry_price"] == 2.5
    assert body["net_debit_credit"] == pytest.approx(250.0)
    t = _get(session_factory, tid)
    assert t.limit_price == 2.5
    assert t.legs[0]["entry_price"] == 2.5


def test_modify_time_in_force(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], time_in_force="gtc")
    res = auth_client.patch(
        f"/api/journal/trades/{tid}/order", json={"time_in_force": "day"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["time_in_force"] == "day"
    # Untouched fields survive the modification.
    assert res.json()["limit_price"] == 1.0
    assert _get(session_factory, tid).time_in_force == "day"


def test_modify_stop_limit_keeps_both_triggers_coherent(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], order_type="stop_limit",
        stop_price=1.5, limit_price=2.0,
    )
    res = auth_client.patch(
        f"/api/journal/trades/{tid}/order",
        json={"stop_price": 1.8, "limit_price": 2.2},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stop_price"] == 1.8
    assert body["limit_price"] == 2.2


def test_modify_rejects_non_working_states(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    for status in ("open", "closed", "cancelled"):
        tid = _seed(session_factory, c["id"], status=status)
        res = auth_client.patch(
            f"/api/journal/trades/{tid}/order", json={"limit_price": 2.0}
        )
        assert res.status_code == 409, f"{status}: {res.text}"


def test_modify_validation(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])  # plain limit order
    # Empty body — nothing to modify.
    assert auth_client.patch(
        f"/api/journal/trades/{tid}/order", json={}
    ).status_code == 400
    # stop_price on a non-stop_limit order breaks trigger coherence.
    assert auth_client.patch(
        f"/api/journal/trades/{tid}/order", json={"stop_price": 1.5}
    ).status_code == 400
    # Prices validated like placement — must be positive.
    assert auth_client.patch(
        f"/api/journal/trades/{tid}/order", json={"limit_price": -1.0}
    ).status_code == 422
    assert auth_client.patch(
        f"/api/journal/trades/{tid}/order", json={"limit_price": 0}
    ).status_code == 422
    # Foreign/nonexistent trade → 404.
    assert auth_client.patch(
        "/api/journal/trades/999999/order", json={"limit_price": 1.0}
    ).status_code == 404


def test_modify_cascades_to_working_follower_copies(auth_client, session_factory):
    """mirror_modify resolves follower copies the same way mirror_cancel does
    (copied_from_trade_id + still working) and applies the same replace."""
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    res = auth_client.put(
        "/api/combines/copy-config",
        json={
            "lead_combine_id": lead["id"],
            "followers": [{"combine_id": f2["id"], "multiplier": 1.0}],
        },
    )
    assert res.status_code == 200, res.text

    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        lead_tid = _seed(session_factory, lead["id"])
        lead_trade = s.get(Trade, lead_tid)
        mirror_open(s, lead_c, lead_trade)
        copy = s.execute(
            select(Trade).where(Trade.combine_id == f2["id"])
        ).scalars().one()
        copy_id = copy.id
        assert copy.status == "working"

    res = auth_client.patch(
        f"/api/journal/trades/{lead_tid}/order",
        json={"limit_price": 3.0, "time_in_force": "day"},
    )
    assert res.status_code == 200, res.text
    mirrored = _get(session_factory, copy_id)
    assert mirrored.limit_price == 3.0
    assert mirrored.time_in_force == "day"
    assert mirrored.legs[0]["entry_price"] == 3.0
    assert mirrored.status == "working"


def test_modify_leaves_filled_follower_copies_alone(auth_client, session_factory):
    lead = make_combine(auth_client, "50K", name="Lead")
    f2 = make_combine(auth_client, "50K", name="F2")
    auth_client.put(
        "/api/combines/copy-config",
        json={
            "lead_combine_id": lead["id"],
            "followers": [{"combine_id": f2["id"], "multiplier": 1.0}],
        },
    )
    with session_factory() as s:
        lead_c = s.get(Combine, lead["id"])
        lead_tid = _seed(session_factory, lead["id"])
        lead_trade = s.get(Trade, lead_tid)
        mirror_open(s, lead_c, lead_trade)
        copy = s.execute(
            select(Trade).where(Trade.combine_id == f2["id"])
        ).scalars().one()
        copy.status = "open"  # the copy filled before the lead modified
        s.commit()
        copy_id = copy.id

    res = auth_client.patch(
        f"/api/journal/trades/{lead_tid}/order", json={"limit_price": 3.0}
    )
    assert res.status_code == 200, res.text
    mirrored = _get(session_factory, copy_id)
    assert mirrored.limit_price == 1.0            # untouched — already filled
    assert mirrored.legs[0]["entry_price"] == 1.0
