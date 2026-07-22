"""Expiration-day close-out policy — force-flatten before the bell.

Open positions whose last leg dies TODAY are force-closed once the clock is
inside the last `expiry_closeout_minutes` of that session (half-day aware),
and working orders on those contracts are pulled. The sim's alternative to
modeling OCC assignment on physically-settled ETF options.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import models.combine_event  # noqa: F401 — combine_snapshot writes events
from config import settings
from models.trade import Trade
from services.order_monitor import _session_close_for_date, run_order_monitor
from tests.conftest import make_combine

_TODAY = datetime.now(UTC).date()
_CLOSE = _session_close_for_date(_TODAY)  # tz-aware ET close for today
_FEE = settings.per_contract_fee


def _seed(session_factory, combine_id, **kw):
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
        status="open",
    )
    defaults.update(kw)
    legs = defaults.pop("_legs", None)
    expiry = defaults.pop("_expiry", _TODAY.isoformat())
    t = Trade(**defaults)
    t.legs = legs or [
        {
            "side": "call",
            "action": "buy",
            "strike": 100.0,
            "expiry": expiry,
            "contracts": 1,
            "entry_price": 1.0,
        }
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _run(session_factory, now, **kw):
    params = dict(
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 1.0,
        unrealized_for=lambda t, s: 50.0,
        now=now,
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


def _get(session_factory, tid):
    s = session_factory()
    t = s.get(Trade, tid)
    s.close()
    return t


_INSIDE = (_CLOSE - timedelta(minutes=5)).astimezone(UTC)
_BEFORE = (_CLOSE - timedelta(minutes=30)).astimezone(UTC)


def test_closes_position_inside_window(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    summary = _run(session_factory, now=_INSIDE)
    assert summary["closed"] == 1
    t = _get(session_factory, tid)
    assert t.status == "closed"
    assert t.close_reason == "expiry_closeout"
    assert t.realized_pnl is not None
    assert "expiry close-out" in (t.notes or "")


def test_untouched_before_window(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    summary = _run(session_factory, now=_BEFORE)
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


def test_future_expiry_untouched(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tomorrow = (_TODAY + timedelta(days=1)).isoformat()
    tid = _seed(session_factory, c["id"], _expiry=tomorrow)
    summary = _run(session_factory, now=_INSIDE)
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


def test_working_order_pulled_inside_window(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"],
        status="working", order_type="limit", limit_price=0.5,
    )
    # The order must NOT fill inside the window even though its limit is
    # marketable (mark 0.4 ≤ 0.5) — the policy pulls it first.
    summary = _run(session_factory, now=_INSIDE, option_mark=lambda t, s: 0.4)
    assert summary["filled"] == 0
    t = _get(session_factory, tid)
    assert t.status == "cancelled"
    assert "order pulled" in (t.notes or "")


def test_disabled_by_config(auth_client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "expiry_closeout_minutes", 0.0)
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"])
    summary = _run(session_factory, now=_INSIDE)
    assert summary["closed"] == 0
    assert _get(session_factory, tid).status == "open"


def test_idempotent_second_pass(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    _seed(session_factory, c["id"])
    _run(session_factory, now=_INSIDE)
    summary = _run(session_factory, now=_INSIDE)
    assert summary["closed"] == 0


def test_multi_position_flatten_and_realized_math(auth_client, session_factory):
    """Two open books both die at the bell; realized folds the injected
    unrealized minus exit-side commission minus close friction (friction ≥ 0,
    so realized ≤ unrealized − fee)."""
    c = make_combine(auth_client, "50K")
    t1 = _seed(session_factory, c["id"])
    t2 = _seed(session_factory, c["id"], strategy="long_put", _legs=[
        {"side": "put", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 2.0},
    ])
    summary = _run(session_factory, now=_INSIDE)
    assert summary["closed"] == 2
    for tid in (t1, t2):
        t = _get(session_factory, tid)
        assert t.status == "closed" and t.close_reason == "expiry_closeout"
        assert t.realized_pnl is not None
        assert t.realized_pnl <= round(50.0 - _FEE, 2)


def test_pulled_dying_order_cascades_to_follower_copies(auth_client, session_factory):
    """Wave 10: the close-out pull now runs mirror_cancel (the pre-pass
    version silently left follower copies resting on dying contracts)."""
    c = make_combine(auth_client, "50K")
    lead = _seed(
        session_factory, c["id"],
        status="working", order_type="limit", limit_price=0.5,
    )
    follower = _seed(
        session_factory, c["id"],
        status="working", order_type="limit", limit_price=0.5,
        copied_from_trade_id=lead,
    )
    _run(session_factory, now=_INSIDE)
    assert _get(session_factory, lead).status == "cancelled"
    assert _get(session_factory, follower).status == "cancelled"
