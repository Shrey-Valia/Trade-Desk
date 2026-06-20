"""Order monitor logic — fills, auto-closes, OCO, cancel-on-non-tradeable.

All via injected callables (no network): spot_for / option_mark /
unrealized_for / market_open. Trades are seeded straight into the DB.
"""

from __future__ import annotations

from datetime import datetime, timezone

import models.combine_event  # noqa: F401 — ensure combine_events table exists
from models.trade import Trade
from services.order_monitor import (
    _bracket_triggered,
    _entry_fill_triggered,
    run_order_monitor,
)
from tests.conftest import make_combine

_TODAY = datetime.now(timezone.utc).date()


def _seed(session_factory, combine_id, **kw):
    s = session_factory()
    defaults = dict(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        is_paper=True,
        tier="50K",
        combine_id=combine_id,
    )
    defaults.update(kw)
    legs = defaults.pop("_legs", None)
    t = Trade(**defaults)
    t.legs = legs or [
        {
            "side": "call",
            "action": "buy",
            "strike": 100.0,
            "expiry": _TODAY.isoformat(),
            "contracts": 1,
            "entry_price": 1.0,
        }
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _run(session_factory, **kw):
    params = dict(
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 1.0,
        unrealized_for=lambda t, s: 0.0,
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


# --- pure trigger logic -----------------------------------------------------


def test_entry_fill_rules():
    assert _entry_fill_triggered("limit", "buy", 0.8, 1.0)      # mark ≤ limit
    assert not _entry_fill_triggered("limit", "buy", 1.2, 1.0)
    assert _entry_fill_triggered("limit", "sell", 1.2, 1.0)     # mark ≥ limit
    assert _entry_fill_triggered("stop", "buy", 1.2, 1.0)       # mark ≥ stop
    assert _entry_fill_triggered("stop", "sell", 0.8, 1.0)      # mark ≤ stop


def test_bracket_direction_from_entry():
    # level above entry → triggers on the way up
    assert _bracket_triggered(100.0, 105.0, 106.0)
    assert not _bracket_triggered(100.0, 105.0, 104.0)
    # level below entry → triggers on the way down
    assert _bracket_triggered(100.0, 95.0, 94.0)
    assert not _bracket_triggered(100.0, 95.0, 96.0)
    assert not _bracket_triggered(100.0, None, 999.0)


# --- working order fills ----------------------------------------------------


def test_limit_buy_fills_at_limit_when_mark_below(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working", order_type="limit", limit_price=1.0)
    summary = _run(session_factory, option_mark=lambda t, s: 0.80)
    assert summary["filled"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "open"
    assert t.legs[0]["entry_price"] == 1.0  # limit fills AT the limit
    s.close()


def test_limit_buy_does_not_fill_when_mark_above(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working", order_type="limit", limit_price=1.0)
    summary = _run(session_factory, option_mark=lambda t, s: 1.20)
    assert summary["filled"] == 0
    s = session_factory()
    assert s.get(Trade, tid).status == "working"
    s.close()


def test_stop_buy_fills_at_mark(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working", order_type="stop", limit_price=1.0)
    summary = _run(session_factory, option_mark=lambda t, s: 1.30)
    assert summary["filled"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "open"
    assert t.legs[0]["entry_price"] == 1.30  # stop fills at current mark
    s.close()


def test_working_order_cancelled_when_combine_failed(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    # -2_500 realized → balance 47_500 ≤ 48_000 MLL floor → combine fails.
    _seed(
        session_factory,
        c["id"],
        status="closed",
        realized_pnl=-2_500.0,
        exit_date=datetime.now(timezone.utc),
    )
    tid = _seed(session_factory, c["id"], status="working", order_type="limit", limit_price=1.0)
    summary = _run(session_factory, option_mark=lambda t, s: 0.50)  # would otherwise fill
    assert summary["cancelled"] == 1
    assert summary["filled"] == 0
    s = session_factory()
    assert s.get(Trade, tid).status == "cancelled"
    s.close()


# --- bracket auto-closes ----------------------------------------------------


def test_stop_loss_closes_and_books_realized(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", stop_loss=95.0)
    summary = _run(
        session_factory,
        spot_for=lambda sym: 94.0,        # crossed the SL (below entry)
        unrealized_for=lambda t, s: -150.0,
    )
    assert summary["closed"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed"
    assert t.close_reason == "stop_loss"
    assert t.exit_underlying_price == 94.0
    assert t.realized_pnl == -150.65  # −150 − 0.65 exit commission
    s.close()


def test_take_profit_closes(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", take_profit=105.0)
    summary = _run(session_factory, spot_for=lambda sym: 106.0, unrealized_for=lambda t, s: 240.0)
    assert summary["closed"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed" and t.close_reason == "take_profit"
    s.close()


def test_open_without_brackets_is_ignored(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open")  # no SL/TP
    summary = _run(session_factory, spot_for=lambda sym: 80.0, unrealized_for=lambda t, s: -999.0)
    assert summary["closed"] == 0
    s = session_factory()
    assert s.get(Trade, tid).status == "open"
    s.close()


def test_bracket_not_triggered_stays_open(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", stop_loss=95.0, take_profit=105.0)
    summary = _run(session_factory, spot_for=lambda sym: 100.5)  # inside the band
    assert summary["closed"] == 0
    s = session_factory()
    assert s.get(Trade, tid).status == "open"
    s.close()


# --- gating + idempotency ---------------------------------------------------


def test_market_closed_is_a_noop(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working", order_type="limit", limit_price=1.0)
    summary = run_order_monitor(
        session_factory=session_factory,
        market_open=lambda: False,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 0.1,
    )
    assert summary.get("skipped") == "market_closed"
    s = session_factory()
    assert s.get(Trade, tid).status == "working"
    s.close()


def test_idempotent_second_pass_is_noop(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", stop_loss=95.0)
    first = _run(session_factory, spot_for=lambda sym: 94.0, unrealized_for=lambda t, s: -10.0)
    second = _run(session_factory, spot_for=lambda sym: 94.0, unrealized_for=lambda t, s: -10.0)
    assert first["closed"] == 1 and second["closed"] == 0
    s = session_factory()
    assert s.get(Trade, tid).status == "closed"
    s.close()
