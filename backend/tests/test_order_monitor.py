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


# --- stop-limit working orders ----------------------------------------------


def test_stop_limit_does_not_arm_below_stop(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], status="working",
        order_type="stop_limit", stop_price=1.5, limit_price=1.6,
    )
    summary = _run(session_factory, option_mark=lambda t, s: 1.0)  # below stop
    assert summary["filled"] == 0
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "working"
    assert t.order_type == "stop_limit"  # still unarmed
    s.close()


def test_stop_limit_arms_then_fills_at_limit(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], status="working",
        order_type="stop_limit", stop_price=1.5, limit_price=1.6,
    )
    # Mark crosses the stop (≥1.5) AND satisfies the buy-limit (≤1.6) → fills
    # at the resting limit price in the same tick it arms.
    summary = _run(session_factory, option_mark=lambda t, s: 1.55)
    assert summary["filled"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "open"
    assert t.order_type == "limit"  # armed → converted to a resting limit
    assert t.legs[0]["entry_price"] == 1.6  # filled AT the limit
    s.close()


def test_stop_limit_arms_then_rests_when_limit_unmet(auth_client, session_factory):
    c = make_combine(auth_client, "50K")
    tid = _seed(
        session_factory, c["id"], status="working",
        order_type="stop_limit", stop_price=1.5, limit_price=1.6,
    )
    # Mark blows through both the stop and the limit (1.9 > 1.6): the stop arms
    # but the buy-limit (mark ≤ 1.6) is NOT met → rests as a limit, no fill.
    summary = _run(session_factory, option_mark=lambda t, s: 1.9)
    assert summary["filled"] == 0
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "working"
    assert t.order_type == "limit"  # armed but resting
    s.close()
    # A later tick where the mark pulls back into the limit fills it.
    summary2 = _run(session_factory, option_mark=lambda t, s: 1.55)
    assert summary2["filled"] == 1
    s = session_factory()
    assert s.get(Trade, tid).status == "open"
    s.close()


# --- trailing stops ---------------------------------------------------------


def test_trailing_stop_long_trails_up_then_stops_out(auth_client, session_factory):
    """A long position's trail rides a rising mark up, then closes when the
    mark retraces past (high-water − trail_amount)."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", trail_amount=0.5)

    # Tick 1: mark 2.0 → hwm 2.0, trigger 1.5 → no close.
    s1 = _run(session_factory, option_mark=lambda t, s: 2.0)
    assert s1["closed"] == 0
    s = session_factory(); assert s.get(Trade, tid).trail_hwm == 2.0; s.close()

    # Tick 2: mark 2.5 → hwm advances to 2.5, trigger 2.0 → no close.
    s2 = _run(session_factory, option_mark=lambda t, s: 2.5)
    assert s2["closed"] == 0
    s = session_factory(); assert s.get(Trade, tid).trail_hwm == 2.5; s.close()

    # Tick 3: mark 1.9 ≤ trigger 2.0 (hwm stays 2.5) → stop out.
    s3 = _run(session_factory, option_mark=lambda t, s: 1.9, unrealized_for=lambda t, s: 80.0)
    assert s3["closed"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed" and t.close_reason == "stop_loss"
    assert "trailing stop" in (t.notes or "")
    s.close()


def test_trailing_stop_short_trails_down_then_stops_out(auth_client, session_factory):
    """A short position favors a FALLING mark — the trail rides down and closes
    when the mark rebounds past (low-water + trail_amount)."""
    c = make_combine(auth_client, "50K")
    short_leg = [{
        "side": "call", "action": "sell", "strike": 100.0,
        "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 2.0,
    }]
    tid = _seed(session_factory, c["id"], status="open", trail_amount=0.5, _legs=short_leg)

    _run(session_factory, option_mark=lambda t, s: 2.0)   # trough 2.0, trigger 2.5
    _run(session_factory, option_mark=lambda t, s: 1.5)   # trough 1.5, trigger 2.0
    s = session_factory(); assert s.get(Trade, tid).trail_hwm == 1.5; s.close()

    s3 = _run(session_factory, option_mark=lambda t, s: 2.1)  # ≥ 2.0 → stop out
    assert s3["closed"] == 1
    s = session_factory()
    assert s.get(Trade, tid).status == "closed"
    s.close()


def test_trailing_stop_pct_offset(auth_client, session_factory):
    """trail_pct sets the offset as a fraction of the high-water mark."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", trail_pct=0.10)
    # hwm 2.0 → trigger 1.8; mark 1.95 stays above → no close.
    assert _run(session_factory, option_mark=lambda t, s: 2.0)["closed"] == 0
    assert _run(session_factory, option_mark=lambda t, s: 1.95)["closed"] == 0
    # mark 1.79 ≤ 1.8 → stop out.
    assert _run(session_factory, option_mark=lambda t, s: 1.79)["closed"] == 1
    s = session_factory(); assert s.get(Trade, tid).status == "closed"; s.close()


def test_trailing_stop_position_is_monitored_without_fixed_brackets(auth_client, session_factory):
    """A trailing-stop-only open position must NOT be skipped by the
    no-brackets early-continue."""
    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open", trail_amount=0.5)
    # First tick seeds the high-water (proof it was processed, not skipped).
    _run(session_factory, option_mark=lambda t, s: 3.0)
    s = session_factory()
    assert s.get(Trade, tid).trail_hwm == 3.0
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


# --- OCO (one-cancels-the-other) --------------------------------------------


def test_oco_fill_cancels_resting_sibling(auth_client, session_factory):
    """Two working orders in one oco_group: the one whose limit the mark meets
    FILLS; the still-resting sibling is cancelled the same tick."""
    c = make_combine(auth_client, "50K")
    # Buy-limit @1.0 → fills when mark ≤1.0. Sibling buy-limit @0.5 stays resting.
    a = _seed(session_factory, c["id"], status="working", order_type="limit",
              limit_price=1.0, oco_group="g1")
    b = _seed(session_factory, c["id"], status="working", order_type="limit",
              limit_price=0.5, oco_group="g1")
    summary = _run(session_factory, option_mark=lambda t, s: 0.90)
    assert summary["filled"] == 1
    s = session_factory()
    ta, tb = s.get(Trade, a), s.get(Trade, b)
    # Exactly one fills, the other is OCO-cancelled (order-independent).
    statuses = {ta.status, tb.status}
    assert statuses == {"open", "cancelled"}
    cancelled = ta if ta.status == "cancelled" else tb
    assert "OCO cancelled" in (cancelled.notes or "")
    s.close()


def test_oco_independent_groups_do_not_cross_cancel(auth_client, session_factory):
    """A fill in group g1 must not cancel an unrelated order in group g2."""
    c = make_combine(auth_client, "50K")
    a = _seed(session_factory, c["id"], status="working", order_type="limit",
              limit_price=1.0, oco_group="g1")
    other = _seed(session_factory, c["id"], status="working", order_type="limit",
                  limit_price=0.5, oco_group="g2")
    _run(session_factory, option_mark=lambda t, s: 0.90)
    s = session_factory()
    assert s.get(Trade, a).status == "open"
    assert s.get(Trade, other).status == "working"  # untouched
    s.close()


def test_oco_bracket_close_cancels_resting_sibling(auth_client, session_factory):
    """An OPEN position closing on a bracket cancels a resting working sibling
    in the same oco_group (e.g. a paired take-profit limit order)."""
    c = make_combine(auth_client, "50K")
    pos = _seed(session_factory, c["id"], status="open", stop_loss=95.0, oco_group="bracket1")
    tp = _seed(session_factory, c["id"], status="working", order_type="limit",
               limit_price=5.0, oco_group="bracket1")
    summary = _run(
        session_factory,
        spot_for=lambda sym: 94.0,           # crosses the stop
        option_mark=lambda t, s: 1.0,        # leaves the tp limit (≥5) unmet
        unrealized_for=lambda t, s: -50.0,
    )
    assert summary["closed"] == 1
    s = session_factory()
    assert s.get(Trade, pos).status == "closed"
    assert s.get(Trade, tp).status == "cancelled"
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


# --- auto-liquidation at MLL / DLL ------------------------------------------
#
# 50K tier: starting 50,000 · trailing 2,000 → MLL floor 48,000 · DLL 1,500.
# Open positions carry no brackets so ONLY the liquidation pass can act on
# them — isolating the headline behavior from the bracket path.


def test_auto_liquidates_when_urpl_breaches_mll(auth_client, session_factory):
    """Realized balance is at start (50,000); a −2,600 open URPL drops the
    LIVE balance to 47,400 ≤ 48,000 floor → force-close + combine FAILED."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open")  # no brackets
    summary = _run(
        session_factory,
        spot_for=lambda sym: 99.0,
        unrealized_for=lambda t, s: -2_600.0,
    )
    assert summary["liquidated"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed"
    assert t.close_reason == "liquidation"
    # −2,600 unrealized − 0.65 exit commission booked as realized.
    assert t.realized_pnl == -2_600.65
    assert "auto-liquidated" in (t.notes or "")
    assert s.get(Combine, c["id"]).outcome == "failed"
    s.close()


def test_no_liquidation_when_live_balance_above_mll(auth_client, session_factory):
    """A −1,000 open URPL leaves live balance 49,000 > 48,000 floor, and DLL
    used 1,000 < 1,500 budget → nothing is touched."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open")
    summary = _run(
        session_factory,
        spot_for=lambda sym: 99.5,
        unrealized_for=lambda t, s: -1_000.0,
    )
    assert summary["liquidated"] == 0
    s = session_factory()
    assert s.get(Trade, tid).status == "open"
    assert s.get(Combine, c["id"]).outcome == "active"
    s.close()


def test_auto_liquidates_when_open_loss_exhausts_dll(auth_client, session_factory):
    """No realized loss, but a −1,500 open loss exhausts the 1,500 DLL budget
    while balance 48,500 stays above the 48,000 MLL floor → DLL-path liquidation."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open")
    summary = _run(
        session_factory,
        spot_for=lambda sym: 99.0,
        unrealized_for=lambda t, s: -1_500.0,
    )
    assert summary["liquidated"] == 1
    s = session_factory()
    t = s.get(Trade, tid)
    assert t.status == "closed" and t.close_reason == "liquidation"
    assert "daily loss limit" in (t.notes or "")
    assert s.get(Combine, c["id"]).outcome == "failed"
    s.close()


def test_auto_liquidation_closes_all_positions_on_combine(auth_client, session_factory):
    """Aggregate URPL across MULTIPLE open positions drives the breach; ALL of
    them are flattened in one tick. Two −1,400 positions = −2,800 live → 47,200."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    t1 = _seed(session_factory, c["id"], status="open")
    t2 = _seed(session_factory, c["id"], status="open")
    summary = _run(
        session_factory,
        spot_for=lambda sym: 99.0,
        unrealized_for=lambda t, s: -1_400.0,
    )
    assert summary["liquidated"] == 2
    s = session_factory()
    assert s.get(Trade, t1).status == "closed"
    assert s.get(Trade, t2).status == "closed"
    assert s.get(Combine, c["id"]).outcome == "failed"
    s.close()


def test_auto_liquidation_idempotent_second_pass(auth_client, session_factory):
    """After a liquidation, a second identical tick finds no OPEN positions →
    no further liquidations and the combine stays failed."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    _seed(session_factory, c["id"], status="open")
    first = _run(session_factory, spot_for=lambda sym: 99.0, unrealized_for=lambda t, s: -2_600.0)
    second = _run(session_factory, spot_for=lambda sym: 99.0, unrealized_for=lambda t, s: -2_600.0)
    assert first["liquidated"] == 1 and second["liquidated"] == 0
    s = session_factory()
    assert s.get(Combine, c["id"]).outcome == "failed"
    s.close()


def test_auto_liquidation_skips_when_spot_unavailable(auth_client, session_factory):
    """A cold feed (spot None) must NOT liquidate on partial information."""
    from models.combine import Combine

    c = make_combine(auth_client, "50K")
    tid = _seed(session_factory, c["id"], status="open")
    summary = _run(
        session_factory,
        spot_for=lambda sym: None,
        unrealized_for=lambda t, s: -9_999.0,
    )
    assert summary["liquidated"] == 0
    s = session_factory()
    assert s.get(Trade, tid).status == "open"
    assert s.get(Combine, c["id"]).outcome == "active"
    s.close()


def test_auto_liquidation_cascades_to_follower_copies(auth_client, session_factory):
    """A lead-combine liquidation books a close that cascades via mirror_close
    to the follower's still-open copy."""
    from models.combine import Combine
    from sqlalchemy import select as _select

    lead = make_combine(auth_client, "50K", name="Lead")
    follower = make_combine(auth_client, "50K", name="Follower")
    res = auth_client.put(
        "/api/combines/copy-config",
        json={
            "lead_combine_id": lead["id"],
            "followers": [{"combine_id": follower["id"], "multiplier": 1.0}],
        },
    )
    assert res.status_code == 200, res.text

    # Open on the lead through the real endpoint path so the copy is mirrored.
    from services.copy_trade import mirror_open

    s = session_factory()
    lead_c = s.get(Combine, lead["id"])
    lead_trade = Trade(
        symbol="SPY",
        strategy="long_call",
        entry_date=datetime.now(timezone.utc),
        entry_underlying_price=100.0,
        net_debit_credit=0.0,
        status="open",
        is_paper=True,
        tier="50K",
        combine_id=lead["id"],
    )
    lead_trade.legs = [
        {"side": "call", "action": "buy", "strike": 100.0,
         "expiry": _TODAY.isoformat(), "contracts": 1, "entry_price": 1.0}
    ]
    s.add(lead_trade)
    s.commit()
    mirror_open(s, lead_c, lead_trade)
    lead_id = lead_trade.id
    s.close()

    summary = _run(
        session_factory,
        spot_for=lambda sym: 99.0,
        unrealized_for=lambda t, s: -2_600.0,
    )
    assert summary["liquidated"] >= 1
    s = session_factory()
    copy = s.execute(
        _select(Trade).where(Trade.copied_from_trade_id == lead_id)
    ).scalars().one()
    # The follower copy is flattened either by the lead's mirror_close cascade
    # ("copy") or by the follower combine's own MLL breach ("liquidation") —
    # ordering decides which fires first. Either way it must end up closed.
    assert copy.status == "closed"
    assert copy.close_reason in ("copy", "liquidation")
    s.close()
