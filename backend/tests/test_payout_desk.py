"""Payout adjudication desk — state machine, money invariants, and the
production compliance gates.

Three sections:

1. STATE MACHINE (services/payout_desk.decide): every legal transition and
   every illegal one (409 invalid_transition), unknown reason codes (422),
   and the auto-approve pass's guardrails (skips under_review/held, honors
   settings.payout_auto_approve, window boundary, reviewer_id=None).

2. MONEY INVARIANTS: the request is the ONLY debit and the denial the ONLY
   credit. request→deny→re-request leaves the ledger exactly as if the
   first request never happened; approve/hold/mark_paid move nothing; a
   denied request stops counting toward the funded-termination MLL math;
   double-deny is impossible (so the re-credit can't double-book).

3. GATES (@pytest.mark.real_gates — production defaults, no relax fixture):
   suspended account, KYC/tax/method prerequisites on payout, the signed
   funded-trader agreement on activation, and ToS+risk consent on
   purchase/reset, each cleared through the real endpoints
   (tests/conftest.satisfy_payout_prereqs / accept_legal).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import routers.combines as combines_router
from config import settings
from database import get_session
from jobs.settle_combines import settle_combines
from models.combine import Combine
from models.combine_event import CombineEvent
from models.payout_request import PayoutRequest
from models.trade import Trade
from models.user import User
from services.payout_desk import DENIAL_REASONS, auto_approve_pass, decide
from tests.conftest import (
    accept_legal,
    make_combine,
    satisfy_payout_prereqs,
    sign_funded_agreement,
)

_PT = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------------------
# Scaffolding (same funded-combine shortcut as test_payout_integrity)
# ---------------------------------------------------------------------------


def _noon_on(day_offset: int) -> datetime:
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


def _session(client):
    return next(client.app.dependency_overrides[get_session]())


def _fund_and_activate(client, combine_id: int, total_profit: float) -> None:
    """FUNDED + ACTIVATED with `total_profit` of funded-stage realized P&L
    spread across five winning days (≥ $150 each), epoch stamped before the
    seeded trades — payout policy gates all clear."""
    session = _session(client)
    per_day = round(total_profit / 5, 2)
    for offset in range(5, 1, -1):
        _seed_closed(session, combine_id, per_day, _noon_on(offset))
    _seed_closed(
        session, combine_id, round(total_profit - 4 * per_day, 2), _noon_on(1)
    )
    combine = session.get(Combine, combine_id)
    epoch = _noon_on(6)
    combine.outcome = "passed"
    combine.funded_at = epoch
    combine.funded_activated_at = epoch
    combine.funded_epoch_at = epoch
    session.add(combine)
    session.commit()
    session.close()


def _request_payout(client, combine_id: int, amount: float | None = None) -> dict:
    body = None if amount is None else {"amount": amount}
    res = client.post(f"/api/combines/{combine_id}/payout", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _the_request(client, combine_id: int) -> PayoutRequest:
    session = _session(client)
    row = session.execute(
        select(PayoutRequest)
        .where(PayoutRequest.combine_id == combine_id)
        .order_by(PayoutRequest.id.desc())
    ).scalars().first()
    session.close()
    assert row is not None
    return row


def _events_of(client, combine_id: int, type_: str) -> list[CombineEvent]:
    session = _session(client)
    rows = (
        session.execute(
            select(CombineEvent)
            .where(CombineEvent.combine_id == combine_id, CombineEvent.type == type_)
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


def _decide(client, request_id: int, action: str, **kwargs) -> PayoutRequest:
    session = _session(client)
    try:
        return decide(
            session,
            request_id,
            action,
            reviewer_id=kwargs.pop("reviewer_id", 99),
            **kwargs,
        )
    finally:
        session.close()


def _no_pacing(monkeypatch) -> None:
    monkeypatch.setattr(combines_router, "PAYOUT_IDEMPOTENCY_WINDOW_S", 0)
    monkeypatch.setattr(combines_router, "PAYOUT_MIN_INTERVAL_H", 0)


# ---------------------------------------------------------------------------
# 1a. Request creation — the workflow row lands with the ledger event
# ---------------------------------------------------------------------------


def test_request_creates_workflow_row_matching_the_event(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    out = _request_payout(auth_client, c["id"])
    assert out["amount"] == 2_400.0  # 0.80 × 3,000

    row = _the_request(auth_client, c["id"])
    assert row.state == "requested"
    assert float(row.amount) == 2_400.0
    assert row.reviewer_id is None and row.decided_at is None
    events = _events_of(auth_client, c["id"], "payout_requested")
    assert len(events) == 1
    assert float(events[0].amount) == float(row.amount)  # amounts NEVER diverge

    # Trader-facing surface: GET /payout-requests shows the same row.
    res = auth_client.get(f"/api/combines/{c['id']}/payout-requests")
    assert res.status_code == 200, res.text
    (item,) = res.json()
    assert item["id"] == row.id
    assert item["amount"] == 2_400.0
    assert item["state"] == "requested"
    assert item["reason_code"] is None and item["reason_label"] is None
    assert item["decided_at"] is None


def test_payout_requests_list_is_owner_scoped(auth_client, second_user_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"])
    # Non-owner: 404, existence not leaked.
    res = second_user_client.get(f"/api/combines/{c['id']}/payout-requests")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 1b. State machine — every legal transition, every illegal one
# ---------------------------------------------------------------------------


def _funded_request(client) -> tuple[dict, PayoutRequest]:
    c = make_combine(client, "50K")
    _fund_and_activate(client, c["id"], 3_000.0)
    _request_payout(client, c["id"])
    return c, _the_request(client, c["id"])


def test_approve_stamps_reviewer_and_echoes_event(auth_client):
    c, row = _funded_request(auth_client)
    out = _decide(auth_client, row.id, "approve", reviewer_id=7)
    assert out.state == "approved"
    assert out.reviewer_id == 7
    assert out.decided_at is not None
    events = _events_of(auth_client, c["id"], "payout_approved")
    assert len(events) == 1 and float(events[0].amount) == 2_400.0


def test_deny_stores_reason_and_note(auth_client):
    c, row = _funded_request(auth_client)
    out = _decide(
        auth_client, row.id, "deny", reason_code="sim_exploit", note="latency abuse"
    )
    assert out.state == "denied"
    assert out.reason_code == "sim_exploit"
    assert out.note == "latency abuse"
    assert out.reviewer_id == 99 and out.decided_at is not None
    (ev,) = _events_of(auth_client, c["id"], "payout_denied")
    assert float(ev.amount) == 2_400.0
    assert DENIAL_REASONS["sim_exploit"] in ev.message
    # Surfaced to the trader with the human label.
    (item,) = auth_client.get(f"/api/combines/{c['id']}/payout-requests").json()
    assert item["state"] == "denied"
    assert item["reason_label"] == DENIAL_REASONS["sim_exploit"]
    assert item["note"] == "latency abuse"


def test_deny_unknown_or_missing_reason_code_is_422(auth_client):
    c, row = _funded_request(auth_client)
    for bad in ("not_a_reason", None):
        with pytest.raises(HTTPException) as exc:
            _decide(auth_client, row.id, "deny", reason_code=bad)
        assert exc.value.status_code == 422
        assert "unknown_reason_code" in exc.value.detail
    # Nothing moved: still requested, no denial event.
    assert _the_request(auth_client, c["id"]).state == "requested"
    assert _events_of(auth_client, c["id"], "payout_denied") == []


def test_hold_resume_review_then_approve(auth_client):
    c, row = _funded_request(auth_client)
    assert _decide(auth_client, row.id, "hold", note="needs a look").state == "held"
    assert _decide(auth_client, row.id, "resume_review").state == "under_review"
    assert _decide(auth_client, row.id, "approve").state == "approved"
    # hold/resume wrote no ledger events; approve wrote exactly one.
    assert len(_events_of(auth_client, c["id"], "payout_approved")) == 1


def test_held_request_can_be_denied_directly(auth_client):
    c, row = _funded_request(auth_client)
    _decide(auth_client, row.id, "hold")
    out = _decide(auth_client, row.id, "deny", reason_code="rule_breach")
    assert out.state == "denied"


def test_mark_paid_only_from_approved(auth_client):
    c, row = _funded_request(auth_client)
    _decide(auth_client, row.id, "approve")
    assert _decide(auth_client, row.id, "mark_paid").state == "paid"


@pytest.mark.parametrize(
    ("setup_actions", "state", "illegal"),
    [
        # requested: mark_paid / resume_review are out of order.
        ([], "requested", ["mark_paid", "resume_review"]),
        # approved: only mark_paid remains.
        (["approve"], "approved", ["approve", "deny", "hold", "resume_review"]),
        # denied is terminal.
        ([("deny", "rule_breach")], "denied",
         ["approve", "deny", "hold", "resume_review", "mark_paid"]),
        # paid is terminal.
        (["approve", "mark_paid"], "paid",
         ["approve", "deny", "hold", "resume_review", "mark_paid"]),
        # under_review: resume_review is not re-applicable, mark_paid early.
        (["hold", "resume_review"], "under_review", ["mark_paid", "resume_review"]),
    ],
)
def test_illegal_transitions_409(auth_client, setup_actions, state, illegal):
    c, row = _funded_request(auth_client)
    for action in setup_actions:
        if isinstance(action, tuple):
            _decide(auth_client, row.id, action[0], reason_code=action[1])
        else:
            _decide(auth_client, row.id, action)
    assert _the_request(auth_client, c["id"]).state == state
    for action in illegal:
        with pytest.raises(HTTPException) as exc:
            _decide(auth_client, row.id, action, reason_code="rule_breach")
        assert exc.value.status_code == 409, (state, action)
        assert exc.value.detail.startswith("invalid_transition"), (state, action)
    # The failed attempts changed nothing.
    assert _the_request(auth_client, c["id"]).state == state


def test_decide_unknown_action_422_and_missing_request_404(auth_client):
    _funded_request(auth_client)
    session = _session(auth_client)
    with pytest.raises(HTTPException) as exc:
        decide(session, 1, "escalate", reviewer_id=1)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        decide(session, 999_999, "approve", reviewer_id=1)
    assert exc.value.status_code == 404
    session.close()


# ---------------------------------------------------------------------------
# 1c. Auto-approve pass
# ---------------------------------------------------------------------------


def _backdate_request(client, request_id: int, hours: float) -> None:
    session = _session(client)
    row = session.get(PayoutRequest, request_id)
    row.requested_at = datetime.now(timezone.utc) - timedelta(hours=hours)
    session.add(row)
    session.commit()
    session.close()


def test_auto_approve_only_past_window_and_only_requested(auth_client):
    c, row = _funded_request(auth_client)
    session = _session(auth_client)
    # Inside the (default 1h) window: untouched.
    assert auto_approve_pass(session) == 0
    session.close()
    assert _the_request(auth_client, c["id"]).state == "requested"

    _backdate_request(auth_client, row.id, hours=2.0)
    session = _session(auth_client)
    assert auto_approve_pass(session) == 1
    # Idempotent: the row is approved now, a re-run finds nothing.
    assert auto_approve_pass(session) == 0
    session.close()
    out = _the_request(auth_client, c["id"])
    assert out.state == "approved"
    assert out.reviewer_id is None  # the system, not a human
    assert out.decided_at is not None
    assert len(_events_of(auth_client, c["id"], "payout_approved")) == 1


@pytest.mark.parametrize("parked_state", ["under_review", "held"])
def test_auto_approve_never_touches_reviewed_rows(auth_client, parked_state):
    c, row = _funded_request(auth_client)
    _decide(auth_client, row.id, "hold")
    if parked_state == "under_review":
        _decide(auth_client, row.id, "resume_review")
    _backdate_request(auth_client, row.id, hours=48.0)  # way past any window

    session = _session(auth_client)
    assert auto_approve_pass(session, review_window_h=0) == 0
    session.close()
    assert _the_request(auth_client, c["id"]).state == parked_state


def test_auto_approve_respects_settings_toggle(auth_client, monkeypatch):
    c, row = _funded_request(auth_client)
    _backdate_request(auth_client, row.id, hours=48.0)
    monkeypatch.setattr(settings, "payout_auto_approve", False)
    session = _session(auth_client)
    assert auto_approve_pass(session, review_window_h=0) == 0
    session.close()
    assert _the_request(auth_client, c["id"]).state == "requested"


def test_auto_approve_window_boundary(auth_client, monkeypatch):
    """A request EXACTLY window-old approves (<= cutoff); a hair newer waits."""
    monkeypatch.setattr(settings, "payout_review_window_h", 1.0)
    c, row = _funded_request(auth_client)
    now = datetime.now(timezone.utc)

    _backdate_request(auth_client, row.id, hours=0.999)  # just inside the window
    session = _session(auth_client)
    assert auto_approve_pass(session, now=now) == 0
    session.close()

    session = _session(auth_client)
    db_row = session.get(PayoutRequest, row.id)
    db_row.requested_at = now - timedelta(hours=1.0)  # exactly at the boundary
    session.commit()
    assert auto_approve_pass(session, now=now) == 1
    session.close()


def test_settle_job_skips_held_rows(auth_client, session_factory, monkeypatch):
    import jobs.settle_combines as settle_module

    monkeypatch.setattr(settle_module, "PAYOUT_REVIEW_WINDOW_H", 0.0)
    c, row = _funded_request(auth_client)
    _decide(auth_client, row.id, "hold")
    summary = settle_combines(session_factory=session_factory)
    assert summary["payouts_approved"] == 0
    assert _the_request(auth_client, c["id"]).state == "held"


# ---------------------------------------------------------------------------
# 2. Money invariants
# ---------------------------------------------------------------------------


def test_request_debits_available_and_balance(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    before = _card(auth_client, c["id"])
    assert before["payout_eligible"] == 2_400.0
    _request_payout(auth_client, c["id"], amount=1_000.0)
    after = _card(auth_client, c["id"])
    assert after["payout_requested"] == 1_000.0
    assert after["payout_eligible"] == pytest.approx(1_400.0)
    assert after["balance"] == pytest.approx(before["balance"] - 1_000.0)


def test_deny_recredits_exactly_and_full_rerequest_succeeds(auth_client, monkeypatch):
    """THE invariant: request → deny → re-request of the SAME amount leaves
    the ledger exactly as if the first request never happened."""
    _no_pacing(monkeypatch)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    virgin = _card(auth_client, c["id"])

    _request_payout(auth_client, c["id"])  # full 2,400
    row = _the_request(auth_client, c["id"])
    _decide(auth_client, row.id, "deny", reason_code="news_window_abuse")

    # Balance, available, and the requested ledger all read as before.
    after_deny = _card(auth_client, c["id"])
    assert after_deny["balance"] == pytest.approx(virgin["balance"])
    assert after_deny["payout_eligible"] == pytest.approx(virgin["payout_eligible"])
    assert after_deny["payout_requested"] == 0.0

    # The full amount is requestable again — and books at full size.
    out = _request_payout(auth_client, c["id"])
    assert out["amount"] == 2_400.0
    final = _card(auth_client, c["id"])
    assert final["payout_requested"] == 2_400.0
    assert final["balance"] == pytest.approx(virgin["balance"] - 2_400.0)


def test_approve_hold_and_mark_paid_move_no_money(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"])
    held = _card(auth_client, c["id"])  # debit already booked at request time
    row = _the_request(auth_client, c["id"])

    for action in ("hold", "resume_review", "approve", "mark_paid"):
        _decide(auth_client, row.id, action)
        now = _card(auth_client, c["id"])
        assert now["balance"] == held["balance"], action
        assert now["payout_requested"] == held["payout_requested"], action
        assert now["payout_eligible"] == held["payout_eligible"], action


def test_denied_request_does_not_count_toward_funded_termination(auth_client):
    """The MLL fail test reads balance NET of payouts. A pending request's
    debit can push a subsequent loss through the floor — a DENIED request
    must not. Same combine shape both times: +3,000 profit, full 2,400
    request, then a −2,700 loss (50,000+3,000−2,700 = 50,300 > 48,000 MLL
    without the debit; 47,900 ≤ MLL with it)."""
    # Control: with the debit outstanding, the loss terminates the account.
    doomed = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, doomed["id"], 3_000.0)
    _request_payout(auth_client, doomed["id"])
    session = _session(auth_client)
    _seed_closed(session, doomed["id"], -2_700.0, datetime.now(timezone.utc))
    session.commit()
    session.close()
    assert _card(auth_client, doomed["id"])["outcome"] == "failed"

    # Same shape, but the request is DENIED before the loss: account survives.
    saved = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, saved["id"], 3_000.0)
    _request_payout(auth_client, saved["id"])
    _decide(
        auth_client,
        _the_request(auth_client, saved["id"]).id,
        "deny",
        reason_code="rule_breach",
    )
    session = _session(auth_client)
    _seed_closed(session, saved["id"], -2_700.0, datetime.now(timezone.utc))
    session.commit()
    session.close()
    assert _card(auth_client, saved["id"])["outcome"] == "passed"


def test_double_deny_impossible_so_recredit_cannot_double(auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    virgin_balance = _card(auth_client, c["id"])["balance"]
    _request_payout(auth_client, c["id"])
    row = _the_request(auth_client, c["id"])
    _decide(auth_client, row.id, "deny", reason_code="other", note="ops call")
    with pytest.raises(HTTPException) as exc:
        _decide(auth_client, row.id, "deny", reason_code="other")
    assert exc.value.status_code == 409
    # Exactly ONE re-credit event; the balance is restored, not inflated.
    assert len(_events_of(auth_client, c["id"], "payout_denied")) == 1
    assert _card(auth_client, c["id"])["balance"] == pytest.approx(virgin_balance)


def test_partial_deny_nets_only_that_request(auth_client, monkeypatch):
    """Two live requests; denying one re-credits ITS amount only."""
    _no_pacing(monkeypatch)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"], amount=1_000.0)
    first = _the_request(auth_client, c["id"])
    _request_payout(auth_client, c["id"], amount=800.0)

    _decide(auth_client, first.id, "deny", reason_code="correlated_trading")
    card = _card(auth_client, c["id"])
    assert card["payout_requested"] == pytest.approx(800.0)
    assert card["payout_eligible"] == pytest.approx(1_600.0)  # 2,400 − 800
    assert card["balance"] == pytest.approx(52_200.0)  # 50,000 + 3,000 − 800


# ---------------------------------------------------------------------------
# 3. Gates — production defaults, real endpoints end-to-end
# ---------------------------------------------------------------------------


def _suspend(client) -> None:
    session = _session(client)
    user = session.execute(
        select(User).where(User.email == "trader@test.local")
    ).scalar_one()
    user.suspended_at = datetime.now(timezone.utc)
    session.add(user)
    session.commit()
    session.close()


@pytest.mark.real_gates
def test_payout_walks_each_verification_gate(auth_client):
    accept_legal(auth_client)  # purchase gate first — subject here is payout
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    path = f"/api/combines/{c['id']}/payout"

    res = auth_client.post(path)
    assert res.status_code == 403 and "kyc_required" in res.json()["detail"]

    r = auth_client.post(
        "/api/verification/kyc/submit",
        json={
            "legal_name": "Test Trader",
            "dob": "1990-01-15",
            "country": "US",
            "document_type": "passport",
        },
    )
    assert r.json()["status"] == "verified"
    res = auth_client.post(path)
    assert res.status_code == 403 and "tax_profile_required" in res.json()["detail"]

    auth_client.post(
        "/api/verification/tax/submit",
        json={
            "form_type": "W9",
            "legal_name": "Test Trader",
            "country": "US",
            "address": {
                "line1": "1 Test St",
                "city": "Testville",
                "region": "CA",
                "postal": "94000",
                "country": "US",
            },
        },
    )
    res = auth_client.post(path)
    assert res.status_code == 403 and "payout_method_required" in res.json()["detail"]

    auth_client.post(
        "/api/verification/methods",
        json={
            "type": "ach",
            "label": "Checking",
            "details": {"routing_number": "021000021", "account_last4": "6789"},
        },
    )
    res = auth_client.post(path)
    assert res.status_code == 200, res.text  # every gate cleared → books


@pytest.mark.real_gates
def test_payout_403_when_suspended(auth_client):
    satisfy_payout_prereqs(auth_client)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _suspend(auth_client)
    res = auth_client.post(f"/api/combines/{c['id']}/payout")
    assert res.status_code == 403
    assert "account_suspended" in res.json()["detail"]
    # Nothing booked.
    assert _events_of(auth_client, c["id"], "payout_requested") == []


@pytest.mark.real_gates
def test_activation_requires_signed_agreement(auth_client):
    accept_legal(auth_client)
    c = make_combine(auth_client, "50K")
    # Legit pass: profit target + min days + consistency across two days.
    session = _session(auth_client)
    _seed_closed(session, c["id"], 1_600.0, _noon_on(2))
    _seed_closed(session, c["id"], 1_600.0, _noon_on(1))
    session.commit()
    session.close()
    assert _card(auth_client, c["id"])["funded"] is True

    res = auth_client.post(f"/api/combines/{c['id']}/activate-account")
    assert res.status_code == 403
    assert "agreement_required" in res.json()["detail"]
    # No charge happened: the gate fires BEFORE the fee is booked.
    assert _card(auth_client, c["id"])["funded_activated"] is False

    sign_funded_agreement(auth_client)
    res = auth_client.post(f"/api/combines/{c['id']}/activate-account")
    assert res.status_code == 200, res.text
    assert res.json()["funded_activated"] is True


@pytest.mark.real_gates
def test_activation_403_when_suspended(auth_client):
    satisfy_payout_prereqs(auth_client)
    c = make_combine(auth_client, "50K")
    _suspend(auth_client)
    res = auth_client.post(f"/api/combines/{c['id']}/activate-account")
    assert res.status_code == 403
    assert "account_suspended" in res.json()["detail"]


@pytest.mark.real_gates
def test_purchase_requires_consent_then_succeeds(auth_client):
    res = auth_client.post("/api/combines/purchase", json={"tier": "50K"})
    assert res.status_code == 403
    assert "consent_required" in res.json()["detail"]
    assert auth_client.get("/api/combines").json()["combines"] == []  # nothing provisioned

    accept_legal(auth_client)  # tos + risk via /api/legal/accept
    res = auth_client.post("/api/combines/purchase", json={"tier": "50K"})
    assert res.status_code == 201, res.text


@pytest.mark.real_gates
def test_purchase_403_when_suspended(auth_client):
    accept_legal(auth_client)
    _suspend(auth_client)
    res = auth_client.post("/api/combines/purchase", json={"tier": "50K"})
    assert res.status_code == 403
    assert "account_suspended" in res.json()["detail"]


@pytest.mark.real_gates
def test_reset_requires_consent(auth_client, monkeypatch):
    """Consent accepted at v1, then the ToS version bumps: the reset (a
    purchase — it books a fee) re-gates until re-acceptance."""
    from services import legal as legal_service

    accept_legal(auth_client)
    c = make_combine(auth_client, "50K")
    # Fail the eval so a reset is legal on the merits.
    session = _session(auth_client)
    _seed_closed(session, c["id"], -2_500.0, datetime.now(timezone.utc))
    session.commit()
    session.close()
    assert _card(auth_client, c["id"])["outcome"] == "failed"

    monkeypatch.setitem(legal_service.LEGAL_DOC_VERSIONS, "tos", 2)
    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 403
    assert "consent_required" in res.json()["detail"]

    accept_legal(auth_client)  # re-accept at v2
    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# 4. REVIEW-WAVE REGRESSIONS (adversarial review 2026-07-15): the cross-epoch
#    denial credit, the decide/auto-approve races, lifecycle voiding on
#    reset/refund, and archived-combine payout requests.
# ---------------------------------------------------------------------------


def test_reset_voids_live_payout_requests(auth_client, monkeypatch):
    """A reset sweeps live (requested/under_review/held) payout requests into
    terminal 'cancelled' with NO ledger event — a stale row can never be
    denied later into an orphaned re-credit against the fresh epoch."""
    _no_pacing(monkeypatch)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"], amount=500.0)
    row = _the_request(auth_client, c["id"])
    _decide(auth_client, row.id, "hold")  # pinned against auto-approve

    # Terminate the funded account, then reset it (flat book — seeds are
    # closed trades only).
    session = _session(auth_client)
    combine = session.get(Combine, c["id"])
    combine.outcome = "failed"
    session.add(combine)
    session.commit()
    session.close()
    res = auth_client.post(f"/api/combines/{c['id']}/reset")
    assert res.status_code == 200, res.text

    # The held row is now terminally cancelled with the system reason…
    session = _session(auth_client)
    fresh = session.get(PayoutRequest, row.id)
    assert fresh.state == "cancelled"
    assert fresh.reason_code == "account_reset"
    session.close()
    # …a late denial is impossible…
    with pytest.raises(HTTPException) as exc:
        _decide(auth_client, row.id, "deny", reason_code="rule_breach")
    assert exc.value.status_code == 409
    assert "cancelled" in exc.value.detail
    # …and no re-credit ever hit the ledger.
    assert _events_of(auth_client, c["id"], "payout_denied") == []
    # The trader-facing feed labels the void.
    feed = auth_client.get(f"/api/combines/{c['id']}/payout-requests").json()
    cancelled = next(r for r in feed if r["id"] == row.id)
    assert cancelled["state"] == "cancelled"
    assert cancelled["reason_label"]  # REASON_LABELS covers system codes


def test_stale_epoch_denial_writes_no_ledger_credit(auth_client, monkeypatch):
    """Belt for the cross-epoch hole: if a live request somehow survives into
    a NEWER funded epoch, denying it records history (amount=None event) but
    books NO re-credit — new-epoch debits stay fully counted."""
    from services.combine_state import payouts_booked

    _no_pacing(monkeypatch)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"], amount=500.0)
    stale = _the_request(auth_client, c["id"])

    # Simulate a re-activation stamping a NEW epoch after the request.
    session = _session(auth_client)
    combine = session.get(Combine, c["id"])
    new_epoch = datetime.now(timezone.utc)
    combine.funded_epoch_at = new_epoch
    session.add(combine)
    session.commit()
    session.close()

    _decide(auth_client, stale.id, "deny", reason_code="rule_breach")

    session = _session(auth_client)
    fresh = session.get(PayoutRequest, stale.id)
    assert fresh.state == "denied"
    assert "stale epoch" in (fresh.note or "")
    session.close()
    denied_events = _events_of(auth_client, c["id"], "payout_denied")
    assert len(denied_events) == 1
    assert denied_events[0].amount is None  # history, not money
    # The new epoch's payout math sees NO orphaned credit.
    session = _session(auth_client)
    assert payouts_booked(session, c["id"], since=new_epoch) == 0.0
    session.close()


def test_concurrent_deny_claims_transition_once(auth_client):
    """Two sessions race the same deny: the CAS lets exactly one win — the
    loser 409s and the ledger holds exactly ONE re-credit."""
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"], amount=500.0)
    row = _the_request(auth_client, c["id"])

    # Prime BOTH identity maps with the stale 'requested' row first — the
    # exact widened race window from the review's reproduction.
    s1 = _session(auth_client)
    s2 = _session(auth_client)
    assert s1.get(PayoutRequest, row.id).state == "requested"
    assert s2.get(PayoutRequest, row.id).state == "requested"
    decide(s1, row.id, "deny", reviewer_id=1, reason_code="rule_breach")
    with pytest.raises(HTTPException) as exc:
        decide(s2, row.id, "deny", reviewer_id=2, reason_code="sim_exploit")
    assert exc.value.status_code == 409
    s1.close()
    s2.close()

    denied_events = _events_of(auth_client, c["id"], "payout_denied")
    assert len(denied_events) == 1  # one credit, not two
    session = _session(auth_client)
    fresh = session.get(PayoutRequest, row.id)
    assert fresh.reason_code == "rule_breach"  # the winner's decision stands
    session.close()


def test_auto_approve_loses_race_to_deny(auth_client, monkeypatch):
    """A deny landing before the auto-approve pass claims the row wins: the
    pass's per-row CAS misses and the request stays denied — never
    'approved with the re-credit still booked'."""
    monkeypatch.setattr(settings, "payout_auto_approve", True)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"], amount=500.0)
    row = _the_request(auth_client, c["id"])
    # Age the request past any window.
    session = _session(auth_client)
    fresh = session.get(PayoutRequest, row.id)
    fresh.requested_at = datetime.now(timezone.utc) - timedelta(hours=48)
    session.add(fresh)
    session.commit()
    session.close()

    _decide(auth_client, row.id, "deny", reason_code="rule_breach")

    session = _session(auth_client)
    approved = auto_approve_pass(session, review_window_h=0.0)
    assert approved == 0
    final = session.get(PayoutRequest, row.id)
    assert final.state == "denied"
    session.close()
    assert _events_of(auth_client, c["id"], "payout_approved") == []


def test_auto_approve_skips_archived_and_failed_combines(auth_client, monkeypatch):
    """Lifecycle guard: requests on archived or FAILED combines never
    auto-approve — they wait for a human (or a lifecycle void)."""
    monkeypatch.setattr(settings, "payout_auto_approve", True)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"], amount=500.0)
    row = _the_request(auth_client, c["id"])
    session = _session(auth_client)
    fresh = session.get(PayoutRequest, row.id)
    fresh.requested_at = datetime.now(timezone.utc) - timedelta(hours=48)
    session.add(fresh)
    combine = session.get(Combine, c["id"])
    combine.outcome = "failed"
    session.add(combine)
    session.commit()

    assert auto_approve_pass(session, review_window_h=0.0) == 0

    combine.outcome = "passed"
    combine.status = "archived"
    session.add(combine)
    session.commit()
    assert auto_approve_pass(session, review_window_h=0.0) == 0
    assert session.get(PayoutRequest, row.id).state == "requested"
    session.close()


def test_refund_voids_requests_and_archived_combine_refuses_payouts(
    auth_client, monkeypatch
):
    """A refund/chargeback archives the combine AND voids every live payout
    request — including approved-unpaid — with no ledger events; the
    archived combine then refuses new payout requests outright."""
    from models.payment import Payment
    from routers.payments import _refund_payment

    _no_pacing(monkeypatch)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], 3_000.0)
    _request_payout(auth_client, c["id"], amount=500.0)
    first = _the_request(auth_client, c["id"])
    _decide(auth_client, first.id, "approve")  # approved-unpaid
    _request_payout(auth_client, c["id"], amount=400.0)

    session = _session(auth_client)
    payment = session.execute(
        select(Payment).where(
            Payment.combine_id == c["id"], Payment.status == "paid"
        )
    ).scalars().first()
    assert payment is not None
    denied_before = len(_events_of(auth_client, c["id"], "payout_denied"))
    _refund_payment(session, payment, "charge.refunded")

    rows = session.execute(
        select(PayoutRequest).where(PayoutRequest.combine_id == c["id"])
    ).scalars().all()
    assert {r.state for r in rows} == {"cancelled"}
    assert {r.reason_code for r in rows} == {"chargeback_risk"}
    combine = session.get(Combine, c["id"])
    assert combine.status == "archived"
    session.close()
    # Voiding wrote NO ledger events.
    assert len(_events_of(auth_client, c["id"], "payout_denied")) == denied_before
    # And the archived combine's payout door is closed.
    res = auth_client.post(f"/api/combines/{c['id']}/payout", json={"amount": 100})
    assert res.status_code == 409
    assert "combine_archived" in res.json()["detail"]
