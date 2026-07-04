"""Race guards — state transitions commit via conditional UPDATEs.

The monitor and the API used to mutate the same rows last-writer-wins: a
user cancel landing during the monitor's pricing (network) window was
silently overwritten by the fill, and a manual close racing a bracket
close double-booked realized (+= applied twice). Every transition now
claims the row with `UPDATE … WHERE id=? AND status=?` and skips on
rowcount 0. The races are simulated by flipping the row's status through
a SECOND session from inside the injected pricing callables — exactly the
read → network → commit interleaving the guards exist for.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import models.combine_event  # noqa: F401 — combine_snapshot writes events
import routers.journal as journal_router
from models.trade import Trade
from services.order_monitor import run_order_monitor
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
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}
    ]
    s.add(t)
    s.commit()
    tid = t.id
    s.close()
    return tid


def _flip_status(session_factory, tid, status, **extra):
    """Concurrent writer: commit a status flip through a separate session."""
    s = session_factory()
    t = s.get(Trade, tid)
    t.status = status
    for k, v in extra.items():
        setattr(t, k, v)
    s.commit()
    s.close()


def _get(session_factory, tid) -> Trade:
    s = session_factory()
    t = s.get(Trade, tid)
    s.expunge(t)
    s.close()
    return t


def _run(session_factory, **kw):
    params = dict(
        market_open=lambda: True,
        spot_for=lambda sym: 100.0,
        option_mark=lambda t, s: 1.0,
        unrealized_for=lambda t, s: 0.0,
    )
    params.update(kw)
    return run_order_monitor(session_factory=session_factory, **params)


def test_cancel_during_fill_window_wins(auth_client, session_factory):
    """A user cancel that lands while the monitor is pricing the fill must
    WIN: the fill's conditional claim sees rowcount 0 and skips."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working",
                order_type="limit", limit_price=1.0)

    def mark_and_cancel(t, s):
        # The user's cancel commits inside the monitor's pricing window.
        _flip_status(session_factory, tid, "cancelled")
        return 0.80  # would satisfy the buy limit → fill would fire

    summary = _run(session_factory, option_mark=mark_and_cancel)
    assert summary["filled"] == 0
    t = _get(session_factory, tid)
    assert t.status == "cancelled"                       # not overwritten
    assert t.legs[0]["entry_price"] == 1.0               # placeholder intact
    assert t.entry_underlying_price == 100.0


def test_stop_limit_arming_respects_concurrent_cancel(auth_client, session_factory):
    """The stop→limit ARMING write is also claimed conditionally — a cancel
    during the pricing window keeps the row cancelled and un-armed."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working",
                order_type="stop_limit", stop_price=1.0, limit_price=1.2)

    def mark_and_cancel(t, s):
        _flip_status(session_factory, tid, "cancelled")
        return 1.1  # ≥ stop 1.0 → would arm (and fill vs limit 1.2)

    summary = _run(session_factory, option_mark=mark_and_cancel)
    assert summary["filled"] == 0
    t = _get(session_factory, tid)
    assert t.status == "cancelled"
    assert t.order_type == "stop_limit"                  # never armed


def test_bracket_close_skips_concurrently_closed_trade(auth_client, session_factory):
    """A manual close that lands during the bracket close's unrealized
    recompute must not be double-booked (+= applied twice)."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", take_profit=110.0)

    def unrealized_and_close(t, s):
        # The manual close books first, inside the monitor's window.
        _flip_status(
            session_factory, tid, "closed",
            realized_pnl=50.0, close_reason="manual",
        )
        return 100.0

    summary = _run(
        session_factory,
        spot_for=lambda sym: 111.0,           # bracket triggered
        unrealized_for=unrealized_and_close,
    )
    assert summary["closed"] == 0
    t = _get(session_factory, tid)
    assert t.status == "closed"
    assert t.close_reason == "manual"                    # first close wins
    assert t.realized_pnl == pytest.approx(50.0)          # booked ONCE


def test_patch_close_409s_when_monitor_closed_first(auth_client, session_factory, monkeypatch):
    """The PATCH close claims open→closed conditionally: a bracket close that
    lands during its recompute window returns 409 instead of re-booking."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open")

    def recompute_and_lose(trade):
        # Monitor books the close during the endpoint's recompute window.
        _flip_status(
            session_factory, tid, "closed",
            realized_pnl=77.0, close_reason="take_profit",
        )
        return 123.0

    monkeypatch.setattr(journal_router, "_recompute_unrealized", recompute_and_lose)
    res = auth_client.patch(
        f"/api/journal/trades/{tid}", json={"status": "closed"}
    )
    assert res.status_code == 409
    t = _get(session_factory, tid)
    assert t.realized_pnl == pytest.approx(77.0)          # monitor's booking intact
    assert t.close_reason == "take_profit"


def test_journal_cancel_409s_when_fill_lands_first(auth_client, session_factory, monkeypatch):
    """A monitor fill landing between the cancel endpoint's read and its write
    wins the row: the cancel 409s instead of silently erasing the fill."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="working",
                order_type="limit", limit_price=1.0)

    original = journal_router._owned_trade

    def read_then_filled(session, user, trade_id):
        trade = original(session, user, trade_id)
        # The monitor's fill commits right after the endpoint's read.
        _flip_status(session_factory, tid, "open")
        return trade

    monkeypatch.setattr(journal_router, "_owned_trade", read_then_filled)
    res = auth_client.post(f"/api/journal/trades/{tid}/cancel")
    assert res.status_code == 409
    assert _get(session_factory, tid).status == "open"    # fill preserved
