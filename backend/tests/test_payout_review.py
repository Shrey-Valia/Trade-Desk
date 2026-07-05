"""Payout review states — request → simulated review → approval.

`request_payout` books a 'payout_requested' event; the DEBIT happens at
REQUEST time (funds are held — combine_state.PAYOUT_DEBIT_TYPES), so the
balance, HWM basis, and eligibility all move immediately. The settle pass
(jobs/settle_combines.approve_pending_payouts) then approves requests older
than the review window by recording a 'payout_approved' with the same
amount — bookkeeping only, never a second debit. Legacy terminal 'payout'
events (old data) still count as debits and need no approval.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import jobs.settle_combines as settle_module
from database import get_session
from jobs.settle_combines import approve_pending_payouts, settle_combines
from models.combine import Combine
from models.combine_event import CombineEvent
from models.trade import Trade
from models.user import User
from tests.conftest import make_combine

_PT = ZoneInfo("America/Los_Angeles")


def _et_noon_on(day_offset: int) -> datetime:
    d = (datetime.now(_PT) - timedelta(days=day_offset)).date()
    return datetime.combine(d, time(12, 0), tzinfo=_PT).astimezone(timezone.utc)


def _seed_closed(session, combine_id: int, realized: float, exit_at: datetime) -> None:
    session.add(
        Trade(
            symbol="SPY",
            strategy="long_straddle",
            entry_date=exit_at,
            entry_underlying_price=400.0,
            net_debit_credit=0.0,
            status="closed",
            is_paper=True,
            notes="seed",
            tier="50K",
            combine_id=combine_id,
            exit_date=exit_at,
            exit_underlying_price=400.0,
            realized_pnl=realized,
            legs_json="[]",
        )
    )


def _fund_and_activate(client, combine_id: int, total_profit: float) -> None:
    """FUNDED + ACTIVATED with `total_profit` of funded-stage realized P&L
    spread over five winning days (same shortcut as test_payout_integrity)."""
    session = next(client.app.dependency_overrides[get_session]())
    per_day = round(total_profit / 5, 2)
    for offset in range(5, 1, -1):
        _seed_closed(session, combine_id, per_day, _et_noon_on(offset))
    _seed_closed(
        session, combine_id, round(total_profit - 4 * per_day, 2), _et_noon_on(1)
    )
    combine = session.get(Combine, combine_id)
    epoch = _et_noon_on(6)
    combine.outcome = "passed"
    combine.funded_at = epoch
    combine.funded_activated_at = epoch
    combine.funded_epoch_at = epoch
    session.add(combine)
    session.commit()
    session.close()


def _events_of(client, combine_id: int, type_: str) -> list[CombineEvent]:
    session = next(client.app.dependency_overrides[get_session]())
    rows = (
        session.execute(
            select(CombineEvent)
            .where(
                CombineEvent.combine_id == combine_id, CombineEvent.type == type_
            )
            .order_by(CombineEvent.id)
        )
        .scalars()
        .all()
    )
    session.close()
    return rows


def _card(client, combine_id: int) -> dict:
    return next(
        c for c in client.get("/api/combines").json()["combines"] if c["id"] == combine_id
    )


def _session(client):
    return next(client.app.dependency_overrides[get_session]())


# ---------------------------------------------------------------------------
# Request → pending: the debit happens at request time
# ---------------------------------------------------------------------------


def test_request_books_pending_event_and_debits_immediately(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)

    res = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert res.status_code == 200, res.text
    assert res.json()["amount"] == 2_400.0  # 0.80 × 3,000

    requested = _events_of(auth_client, c["id"], "payout_requested")
    assert len(requested) == 1
    assert float(requested[0].amount) == 2_400.0
    assert "pending review" in requested[0].message
    # Not yet approved — the review window hasn't elapsed.
    assert _events_of(auth_client, c["id"], "payout_approved") == []

    # Funds are HELD from the request instant: balance and the requested
    # ledger both reflect the debit before any approval exists.
    card = _card(auth_client, c["id"])
    assert card["payout_requested"] == 2_400.0
    assert card["balance"] == pytest.approx(50_600.0)  # 50,000 + 3,000 − 2,400


def test_no_approval_inside_review_window(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    auth_client.post(f"/api/combines/{c['id']}/payout")

    session = _session(auth_client)
    approved = approve_pending_payouts(session)  # default 1h window
    session.close()
    assert approved == 0
    assert _events_of(auth_client, c["id"], "payout_approved") == []


# ---------------------------------------------------------------------------
# Approval after the window — bookkeeping only, never a second debit
# ---------------------------------------------------------------------------


def test_approval_after_window_records_event_without_double_debit(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    auth_client.post(f"/api/combines/{c['id']}/payout")
    before = _card(auth_client, c["id"])

    session = _session(auth_client)
    approved = approve_pending_payouts(session, review_window_h=0)
    session.close()
    assert approved == 1

    events = _events_of(auth_client, c["id"], "payout_approved")
    assert len(events) == 1
    assert float(events[0].amount) == 2_400.0
    assert "approved" in events[0].message.lower()

    # The approval moved NOTHING: same balance, same requested total.
    after = _card(auth_client, c["id"])
    assert after["balance"] == before["balance"]
    assert after["payout_requested"] == before["payout_requested"] == 2_400.0


def test_approval_pass_is_idempotent(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    auth_client.post(f"/api/combines/{c['id']}/payout")

    session = _session(auth_client)
    assert approve_pending_payouts(session, review_window_h=0) == 1
    assert approve_pending_payouts(session, review_window_h=0) == 0
    session.close()
    assert len(_events_of(auth_client, c["id"], "payout_approved")) == 1


def test_settle_job_runs_the_approval_pass(auth_client, session_factory, monkeypatch):
    monkeypatch.setattr(settle_module, "PAYOUT_REVIEW_WINDOW_H", 0.0)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    auth_client.post(f"/api/combines/{c['id']}/payout")

    summary = settle_combines(session_factory=session_factory)
    assert summary["payouts_approved"] == 1
    assert len(_events_of(auth_client, c["id"], "payout_approved")) == 1


# ---------------------------------------------------------------------------
# Backward compatibility — legacy terminal 'payout' events
# ---------------------------------------------------------------------------


def test_legacy_payout_events_still_debit_and_need_no_approval(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)

    # Old data: a terminal 'payout' event booked before the review flow.
    session = _session(auth_client)
    user_id = session.execute(
        select(User.id).where(User.email == "trader@test.local")
    ).scalar_one()
    session.add(
        CombineEvent(
            user_id=user_id,
            combine_id=c["id"],
            type="payout",
            message="Payout requested — $500.00.",
            amount=500.0,
        )
    )
    session.commit()

    # Still a debit everywhere: card ledger + balance.
    card = _card(auth_client, c["id"])
    assert card["payout_requested"] == 500.0
    assert card["balance"] == pytest.approx(52_500.0)  # 50,000 + 3,000 − 500
    assert card["payout_eligible"] == pytest.approx(1_900.0)  # 2,400 − 500

    # The approval desk leaves legacy rows alone.
    assert approve_pending_payouts(session, review_window_h=0) == 0
    session.close()
    assert _events_of(auth_client, c["id"], "payout_approved") == []


def test_mixed_legacy_and_new_requests_net_together(auth_client, monkeypatch):
    """A legacy 'payout' and a new 'payout_requested' on the same combine sum
    into one requested total — the eligibility netting can't double-pay."""
    import routers.combines as combines_router

    monkeypatch.setattr(combines_router, "PAYOUT_IDEMPOTENCY_WINDOW_S", 0)
    monkeypatch.setattr(combines_router, "PAYOUT_MIN_INTERVAL_H", 0)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)

    session = _session(auth_client)
    user_id = session.execute(
        select(User.id).where(User.email == "trader@test.local")
    ).scalar_one()
    session.add(
        CombineEvent(
            user_id=user_id,
            combine_id=c["id"],
            type="payout",
            message="Payout requested — $1,000.00.",
            amount=1_000.0,
        )
    )
    session.commit()
    session.close()

    # Only 2,400 − 1,000 = 1,400 remains requestable.
    res = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert res.status_code == 200, res.text
    assert res.json()["amount"] == pytest.approx(1_400.0)
    card = _card(auth_client, c["id"])
    assert card["payout_requested"] == pytest.approx(2_400.0)
    assert card["payout_eligible"] == 0.0
