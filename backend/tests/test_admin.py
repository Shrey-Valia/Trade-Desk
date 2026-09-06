"""Operator back office — /api/admin/* (workstream C2).

Covers: the 403 authz boundary across every endpoint group; user search /
detail shapes (and their PII discipline — no password_hash, no payout-method
details_json, no KYC dob); suspend/unsuspend with the self-suspend refusal;
promote/demote with the last-admin lockout; reset-credit grants against the
pricing cap; the human KYC decision; combine fail/unfail round-trip (the
engine's snapshot agrees after unfail) + extend_billing; the payment refund
(webhook-core reuse: payment refunded + combine archived); the payout review
queue + decisions through the API (deny-without-reason 422 included); the
platform kill switch flipping the LIVE zerodte open gate; metrics; the jobs
health endpoint over run_logged; and the AdminAction audit trail every
mutation must write.

Conventions: admin bootstrap via settings.admin_emails (B1 pattern —
promoted on first admin-endpoint touch); the conftest autouse
_relax_compliance_gates fixture keeps the purchase/payout compliance gates
relaxed (these tests target the admin surface, not the gates); the zerodte
open test stubs market data exactly like test_risk_controls (the autouse
_no_live_option_quotes fixture keeps live quotes off the network).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from config import settings
from database import get_session
from main import app
from models.admin_action import AdminAction
from models.combine import Combine
from models.combine_event import CombineEvent
from models.job_run import JobRun
from models.payment import Payment
from models.trade import Trade
from models.user import User
from services.job_runs import run_logged
from services.pricing import RESET_CREDIT_CAP, monthly_price
from tests.conftest import _signup, make_combine

_PT = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------------------
# Fixtures + scaffolding
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_client(api_client, monkeypatch):
    """An authenticated ADMIN on the same database. Bootstraps through the
    settings.admin_emails allowlist (promoted on first admin-endpoint touch),
    exactly like the first real operator seat — the B1 pattern. Separate
    TestClient so cookie jars don't mix; api_client keeps the get_session
    override installed."""
    monkeypatch.setattr(settings, "admin_emails", ("admin@test.local",))
    c = TestClient(app)
    _signup(c, "admin@test.local")
    return c


def test_me_bootstraps_admin_for_allowlisted_email(api_client, monkeypatch):
    """GET /api/auth/me must apply the admin allowlist bootstrap itself.

    The frontend gates the /admin route on this endpoint's `role` and would
    redirect a not-yet-promoted allow-listed operator away BEFORE any
    /api/admin/* call could trigger promotion — so promoting only inside
    require_admin left the console unreachable via the UI. Regression for the
    demo-blocker found in the 2026-07-27 live dry-run."""
    monkeypatch.setattr(settings, "admin_emails", ("newadmin@test.local",))
    c = TestClient(app)
    _signup(c, "newadmin@test.local")
    # No /api/admin/* call has been made — /me alone must report admin.
    me = c.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_me_does_not_promote_non_allowlisted(api_client, monkeypatch):
    """A normal user is never promoted by /me."""
    monkeypatch.setattr(settings, "admin_emails", ("someoneelse@test.local",))
    c = TestClient(app)
    _signup(c, "regular@test.local")
    assert c.get("/api/auth/me").json()["role"] != "admin"


def _session(client):
    return next(client.app.dependency_overrides[get_session]())


def _user_id(client, email: str) -> int:
    session = _session(client)
    uid = session.execute(select(User.id).where(User.email == email)).scalar_one()
    session.close()
    return uid


def _get_user(client, uid: int) -> User:
    session = _session(client)
    user = session.get(User, uid)
    session.expunge(user)
    session.close()
    return user


def _actions(client, action: str | None = None) -> list[AdminAction]:
    session = _session(client)
    stmt = select(AdminAction).order_by(AdminAction.id)
    if action is not None:
        stmt = stmt.where(AdminAction.action == action)
    rows = session.execute(stmt).scalars().all()
    for r in rows:
        session.expunge(r)
    session.close()
    return rows


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
    for r in rows:
        session.expunge(r)
    session.close()
    return rows


# --- funded-combine shortcut (test_payout_desk pattern) ----------------------


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


def _fund_and_activate(client, combine_id: int, total_profit: float) -> None:
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


def _no_pacing(monkeypatch) -> None:
    import routers.combines as combines_router

    monkeypatch.setattr(combines_router, "PAYOUT_IDEMPOTENCY_WINDOW_S", 0)
    monkeypatch.setattr(combines_router, "PAYOUT_MIN_INTERVAL_H", 0)


# --- zerodte market stub (test_risk_controls pattern) -------------------------


def _stub_market(monkeypatch, bid=1.0, ask=1.2):
    import types

    import routers.zerodte as zerodte

    today = datetime.now(zerodte._ET).date()
    rows = [
        types.SimpleNamespace(
            strike=float(k), type=side, expiry=today,
            bid=bid, ask=ask, last=None, open_interest=None, iv=None,
        )
        for k in (95.0, 100.0, 105.0)
        for side in ("call", "put")
    ]
    monkeypatch.setattr("routers.zerodte.is_market_open", lambda: True)
    monkeypatch.setattr(
        "routers.zerodte.get_chain_snapshot", lambda sym, with_volume=False: rows
    )
    monkeypatch.setattr(
        "routers.zerodte.get_quotes",
        lambda syms: {syms[0]: types.SimpleNamespace(price=100.0)},
    )


def _open_leg(client, symbol: str = "SPY"):
    return client.post(
        "/api/zerodte/open-leg",
        json={"symbol": symbol, "side": "call", "action": "buy",
              "strike": 100, "entry_price": 0},
    )


# ---------------------------------------------------------------------------
# Authz boundary — a representative sample of EVERY endpoint group
# ---------------------------------------------------------------------------

_SAMPLE_ENDPOINTS = [
    ("GET", "/api/admin/users", None),
    ("GET", "/api/admin/users/1", None),
    ("POST", "/api/admin/users/1/suspend", {"reason": "x"}),
    ("POST", "/api/admin/users/1/unsuspend", {}),
    ("POST", "/api/admin/users/1/promote", {}),
    ("POST", "/api/admin/users/1/demote", {}),
    ("POST", "/api/admin/users/1/grant-reset-credit", {"count": 1, "reason": "x"}),
    ("POST", "/api/admin/users/1/kyc/decide", {"approve": True}),
    ("POST", "/api/admin/combines/1/adjust", {"action": "fail", "reason": "x"}),
    ("POST", "/api/admin/payments/1/refund", {"reason": "x"}),
    ("GET", "/api/admin/payouts", None),
    ("POST", "/api/admin/payouts/1/approve", {}),
    ("GET", "/api/admin/platform", None),
    ("PUT", "/api/admin/platform", {"trading_mode": "halted"}),
    ("GET", "/api/admin/metrics", None),
    ("GET", "/api/admin/jobs", None),
    ("GET", "/api/admin/actions", None),
]


def test_every_endpoint_group_403_for_traders(auth_client):
    for method, path, body in _SAMPLE_ENDPOINTS:
        res = auth_client.request(method, path, json=body)
        assert res.status_code == 403, f"{method} {path} → {res.status_code}"
        assert res.json()["detail"] == "admin access required"


def test_admin_endpoints_401_unauthenticated(api_client):
    assert api_client.get("/api/admin/users").status_code == 401
    assert api_client.get("/api/admin/metrics").status_code == 401


# ---------------------------------------------------------------------------
# Users — search / detail
# ---------------------------------------------------------------------------


def test_user_search_pagination_and_shape(admin_client, auth_client):
    make_combine(auth_client, "50K")

    res = admin_client.get("/api/admin/users")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2 and body["page"] == 1
    # Newest first: the trader fixture signs up after the admin fixture.
    assert [u["email"] for u in body["items"]] == [
        "trader@test.local", "admin@test.local",
    ]
    assert "password_hash" not in res.text

    trader = body["items"][0]
    assert trader["combines"] == {"active": 1}
    assert trader["kyc_status"] == "unverified"
    assert trader["reset_credits"] == 0
    assert trader["role"] == "trader"
    assert trader["suspended_at"] is None

    # Search filter + pagination.
    res = admin_client.get("/api/admin/users", params={"q": "trader"})
    assert [u["email"] for u in res.json()["items"]] == ["trader@test.local"]
    res = admin_client.get("/api/admin/users", params={"page": 2, "page_size": 1})
    assert res.json()["total"] == 2
    assert len(res.json()["items"]) == 1
    res = admin_client.get("/api/admin/users", params={"q": "no-such-user"})
    assert res.json() == {"items": [], "total": 0, "page": 1}


def test_user_detail_shape_and_pii_discipline(admin_client, auth_client):
    c = make_combine(auth_client, "50K")
    # KYC (sim auto-verify), a payout method, a support ticket.
    res = auth_client.post(
        "/api/verification/kyc/submit",
        json={"legal_name": "Test Trader", "dob": "1990-01-15",
              "country": "US", "document_type": "passport"},
    )
    assert res.status_code == 200, res.text
    res = auth_client.post(
        "/api/verification/methods",
        json={"type": "ach", "label": "Chase ****6789",
              "details": {"routing_number": "021000021", "account_last4": "6789"}},
    )
    assert res.status_code == 201, res.text
    res = auth_client.post(
        "/api/support/tickets",
        json={"category": "billing", "subject": "Question", "body": "About my bill."},
    )
    assert res.status_code == 201, res.text

    uid = _user_id(admin_client, "trader@test.local")
    res = admin_client.get(f"/api/admin/users/{uid}")
    assert res.status_code == 200, res.text
    detail = res.json()

    assert detail["email"] == "trader@test.local"
    assert detail["active_combine_id"] == c["id"]
    (combine,) = detail["combines"]
    assert combine["tier"] == "50K" and combine["outcome"] == "active"
    assert combine["account_code"] == c["account_code"]
    # The purchase payment ledger row.
    assert detail["payments"][0]["status"] == "paid"
    assert detail["payments"][0]["combine_id"] == c["id"]
    (ticket,) = detail["tickets"]
    assert ticket["subject"] == "Question" and ticket["status"] == "open"
    assert detail["payout_requests"] == []
    # KYC: decision + declared name/country ONLY.
    assert detail["kyc"]["status"] == "verified"
    assert detail["kyc"]["legal_name"] == "Test Trader"
    assert detail["kyc"]["country"] == "US"
    # Payout method: the masked shape only.
    (method,) = detail["payout_methods"]
    assert method == {
        "id": method["id"], "type": "ach", "label": "Chase ****6789",
        "is_default": True, "created_at": method["created_at"],
    }

    # PII discipline: nothing sensitive leaks anywhere in the payload.
    assert "password_hash" not in res.text
    assert "details_json" not in res.text
    assert "021000021" not in res.text  # routing number
    assert "1990-01-15" not in res.text  # KYC dob
    assert "dob" not in detail["kyc"]

    assert admin_client.get("/api/admin/users/999999").status_code == 404


# ---------------------------------------------------------------------------
# Suspend / unsuspend
# ---------------------------------------------------------------------------


def test_suspend_unsuspend_flow_and_audit(admin_client, auth_client):
    uid = _user_id(admin_client, "trader@test.local")
    admin_id = _user_id(admin_client, "admin@test.local")

    res = admin_client.post(
        f"/api/admin/users/{uid}/suspend", json={"reason": "TOS breach"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["suspended_at"] is not None
    assert _get_user(admin_client, uid).suspended_at is not None

    # Already suspended → 409; a blank reason → 422; self-suspend → 422.
    assert (
        admin_client.post(f"/api/admin/users/{uid}/suspend", json={"reason": "x"})
        .status_code == 409
    )
    assert (
        admin_client.post(f"/api/admin/users/{uid}/unsuspend", json={})
        .status_code == 200
    )
    assert _get_user(admin_client, uid).suspended_at is None
    assert (
        admin_client.post(f"/api/admin/users/{uid}/unsuspend", json={})
        .status_code == 409
    )
    assert (
        admin_client.post(f"/api/admin/users/{uid}/suspend", json={"reason": "  "})
        .status_code == 422
    )
    res = admin_client.post(
        f"/api/admin/users/{admin_id}/suspend", json={"reason": "oops"}
    )
    assert res.status_code == 422
    assert res.json()["detail"].startswith("cannot_suspend_self:")

    (suspend,) = _actions(admin_client, "user.suspend")
    assert suspend.actor_id == admin_id
    assert suspend.target_type == "user" and suspend.target_id == uid
    assert suspend.reason == "TOS breach"
    assert '"suspended_at": null' in suspend.before_json
    assert (len(_actions(admin_client, "user.unsuspend"))) == 1


# ---------------------------------------------------------------------------
# Promote / demote
# ---------------------------------------------------------------------------


def test_promote_demote_and_last_admin_guard(admin_client, auth_client):
    uid = _user_id(admin_client, "trader@test.local")
    admin_id = _user_id(admin_client, "admin@test.local")

    res = admin_client.post(f"/api/admin/users/{uid}/promote", json={})
    assert res.status_code == 200 and res.json()["role"] == "admin"
    assert admin_client.post(f"/api/admin/users/{uid}/promote").status_code == 409

    res = admin_client.post(f"/api/admin/users/{uid}/demote", json={})
    assert res.status_code == 200 and res.json()["role"] == "trader"
    assert admin_client.post(f"/api/admin/users/{uid}/demote").status_code == 409

    # The last-admin lockout: an admin can never demote their own account
    # (the only path that could zero the admin count).
    res = admin_client.post(f"/api/admin/users/{admin_id}/demote", json={})
    assert res.status_code == 422
    assert res.json()["detail"].startswith("cannot_demote_self:")
    assert _get_user(admin_client, admin_id).role == "admin"

    assert len(_actions(admin_client, "user.promote")) == 1
    (demote,) = _actions(admin_client, "user.demote")
    assert demote.target_id == uid
    assert '"role": "admin"' in demote.before_json
    assert '"role": "trader"' in demote.after_json


# ---------------------------------------------------------------------------
# Reset-credit grants
# ---------------------------------------------------------------------------


def test_grant_reset_credit_with_cap_and_audit(admin_client, auth_client):
    uid = _user_id(admin_client, "trader@test.local")

    res = admin_client.post(
        f"/api/admin/users/{uid}/grant-reset-credit",
        json={"reason": "goodwill"},  # count defaults to 1
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"id": uid, "reset_credits": 1, "granted": 1}

    # A huge grant clamps at the pricing cap.
    res = admin_client.post(
        f"/api/admin/users/{uid}/grant-reset-credit",
        json={"count": 100, "reason": "make-good"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["reset_credits"] == RESET_CREDIT_CAP
    assert res.json()["granted"] == RESET_CREDIT_CAP - 1
    assert _get_user(admin_client, uid).reset_credits == RESET_CREDIT_CAP

    # At the cap → 409; validation: reason required, count ≥ 1.
    res = admin_client.post(
        f"/api/admin/users/{uid}/grant-reset-credit", json={"reason": "more"}
    )
    assert res.status_code == 409
    assert res.json()["detail"].startswith("reset_credit_cap_reached:")
    assert (
        admin_client.post(
            f"/api/admin/users/{uid}/grant-reset-credit", json={"count": 1}
        ).status_code == 422
    )
    assert (
        admin_client.post(
            f"/api/admin/users/{uid}/grant-reset-credit",
            json={"count": 0, "reason": "x"},
        ).status_code == 422
    )

    grants = _actions(admin_client, "user.grant_reset_credit")
    assert len(grants) == 2
    assert '"reset_credits": 1' in grants[1].before_json
    assert f'"reset_credits": {RESET_CREDIT_CAP}' in grants[1].after_json


# ---------------------------------------------------------------------------
# KYC decision
# ---------------------------------------------------------------------------


def test_kyc_decide_approve_reject_and_audit(admin_client, auth_client, monkeypatch):
    monkeypatch.setattr(settings, "kyc_auto_verify_override", False)
    res = auth_client.post(
        "/api/verification/kyc/submit",
        json={"legal_name": "Test Trader", "dob": "1990-01-15",
              "country": "US", "document_type": "passport"},
    )
    assert res.status_code == 200 and res.json()["status"] == "pending"
    uid = _user_id(admin_client, "trader@test.local")

    res = admin_client.post(
        f"/api/admin/users/{uid}/kyc/decide",
        json={"approve": False, "reason": "Document unreadable"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "rejected"
    assert res.json()["reject_reason"] == "Document unreadable"

    res = admin_client.post(
        f"/api/admin/users/{uid}/kyc/decide", json={"approve": True}
    )
    assert res.status_code == 200
    assert res.json()["status"] == "verified"
    assert res.json()["reject_reason"] is None
    assert res.json()["decided_at"] is not None

    # No submission → the service's 404 surfaces.
    admin_id = _user_id(admin_client, "admin@test.local")
    res = admin_client.post(
        f"/api/admin/users/{admin_id}/kyc/decide", json={"approve": True}
    )
    assert res.status_code == 404

    decisions = _actions(admin_client, "user.kyc_decide")
    assert len(decisions) == 2
    assert '"kyc_status": "pending"' in decisions[0].before_json
    assert '"kyc_status": "rejected"' in decisions[0].after_json
    assert '"kyc_status": "verified"' in decisions[1].after_json


# ---------------------------------------------------------------------------
# Combine adjustments
# ---------------------------------------------------------------------------


def test_combine_fail_unfail_roundtrip_engine_agrees(admin_client, auth_client):
    c = make_combine(auth_client, "50K")

    res = admin_client.post(
        f"/api/admin/combines/{c['id']}/adjust",
        json={"action": "fail", "reason": "prohibited strategy"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "failed"
    # The trader-facing engine snapshot agrees (and stays failed — terminal
    # outcomes are never lazily reverted by combine_snapshot).
    card = next(
        x for x in auth_client.get("/api/combines").json()["combines"]
        if x["id"] == c["id"]
    )
    assert card["outcome"] == "failed"
    (ev,) = _events_of(admin_client, c["id"], "failed")
    assert "manual action by operator" in ev.message

    # Already failed → 409.
    res = admin_client.post(
        f"/api/admin/combines/{c['id']}/adjust",
        json={"action": "fail", "reason": "again"},
    )
    assert res.status_code == 409

    res = admin_client.post(
        f"/api/admin/combines/{c['id']}/adjust",
        json={"action": "unfail", "reason": "dispute upheld"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["outcome"] == "active"
    # Round-trip: the engine recomputes and the combine is active again
    # (balance is far above the MLL, so no lazy re-fail).
    card = next(
        x for x in auth_client.get("/api/combines").json()["combines"]
        if x["id"] == c["id"]
    )
    assert card["outcome"] == "active"
    assert len(_events_of(admin_client, c["id"], "unfailed")) == 1

    # Not failed → 409; blank/missing reason → 422; unknown action → 422.
    assert (
        admin_client.post(
            f"/api/admin/combines/{c['id']}/adjust",
            json={"action": "unfail", "reason": "x"},
        ).status_code == 409
    )
    assert (
        admin_client.post(
            f"/api/admin/combines/{c['id']}/adjust",
            json={"action": "fail", "reason": "   "},
        ).status_code == 422
    )
    assert (
        admin_client.post(
            f"/api/admin/combines/{c['id']}/adjust", json={"action": "fail"}
        ).status_code == 422
    )
    assert (
        admin_client.post(
            f"/api/admin/combines/{c['id']}/adjust",
            json={"action": "explode", "reason": "x"},
        ).status_code == 422
    )
    assert (
        admin_client.post(
            "/api/admin/combines/999999/adjust",
            json={"action": "fail", "reason": "x"},
        ).status_code == 404
    )

    (fail,) = _actions(admin_client, "combine.fail")
    assert fail.target_type == "combine" and fail.target_id == c["id"]
    assert '"outcome": "active"' in fail.before_json
    assert '"outcome": "failed"' in fail.after_json
    (unfail,) = _actions(admin_client, "combine.unfail")
    assert '"outcome": "failed"' in unfail.before_json


def test_extend_billing(admin_client, auth_client):
    c = make_combine(auth_client, "50K")
    session = _session(admin_client)
    before = session.get(Combine, c["id"]).paid_through
    session.close()
    assert before is not None  # seeded by provision_combine

    res = admin_client.post(
        f"/api/admin/combines/{c['id']}/adjust",
        json={"action": "extend_billing", "reason": "outage credit", "days": 30},
    )
    assert res.status_code == 200, res.text
    session = _session(admin_client)
    after = session.get(Combine, c["id"]).paid_through
    session.close()
    assert after - before == timedelta(days=30)

    # days is required and range-checked (1-90).
    for bad in (
        {"action": "extend_billing", "reason": "x"},
        {"action": "extend_billing", "reason": "x", "days": 0},
        {"action": "extend_billing", "reason": "x", "days": 91},
    ):
        assert (
            admin_client.post(
                f"/api/admin/combines/{c['id']}/adjust", json=bad
            ).status_code == 422
        )

    (row,) = _actions(admin_client, "combine.extend_billing")
    assert row.reason == "outage credit"
    assert row.before_json != row.after_json


# ---------------------------------------------------------------------------
# Payment refund
# ---------------------------------------------------------------------------


def test_refund_marks_payment_and_archives_combine(admin_client, auth_client):
    c = make_combine(auth_client, "50K")
    session = _session(admin_client)
    payment_id = session.execute(
        select(Payment.id).where(Payment.combine_id == c["id"])
    ).scalar_one()
    session.close()

    res = admin_client.post(
        f"/api/admin/payments/{payment_id}/refund", json={"reason": "chargeback"}
    )
    assert res.status_code == 200, res.text
    assert res.json() == {
        "id": payment_id, "status": "refunded",
        "combine_id": c["id"], "combine_status": "archived",
    }
    # Ledger + lifecycle: combine archived, active combine repointed (the
    # trader's only combine → None), 'refunded' event booked.
    session = _session(admin_client)
    assert session.get(Combine, c["id"]).status == "archived"
    trader = session.execute(
        select(User).where(User.email == "trader@test.local")
    ).scalar_one()
    assert trader.active_combine_id is None
    session.close()
    assert len(_events_of(admin_client, c["id"], "refunded")) == 1

    # Already refunded → 409; migration grants → 409; missing → 404.
    res = admin_client.post(
        f"/api/admin/payments/{payment_id}/refund", json={"reason": "again"}
    )
    assert res.status_code == 409
    assert res.json()["detail"].startswith("already_refunded:")

    session = _session(admin_client)
    grant = Payment(
        user_id=trader.id, combine_id=None, tier="50K",
        amount=None, status="migration_grant",
    )
    session.add(grant)
    session.commit()
    grant_id = grant.id
    session.close()
    res = admin_client.post(
        f"/api/admin/payments/{grant_id}/refund", json={"reason": "x"}
    )
    assert res.status_code == 409
    assert res.json()["detail"].startswith("not_refundable:")
    assert (
        admin_client.post(
            "/api/admin/payments/999999/refund", json={"reason": "x"}
        ).status_code == 404
    )

    (refund,) = _actions(admin_client, "payment.refund")
    assert refund.target_type == "payment" and refund.target_id == payment_id
    assert '"status": "paid"' in refund.before_json
    assert '"status": "refunded"' in refund.after_json


# ---------------------------------------------------------------------------
# Payout queue + decisions
# ---------------------------------------------------------------------------


def test_payout_queue_listing_with_reviewer_context(admin_client, auth_client):
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], total_profit=3_000.0)
    _request_payout(auth_client, c["id"])  # full eligible: 3000 × 0.8 = 2400

    res = admin_client.get("/api/admin/payouts")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 1
    (item,) = body["items"]
    assert item["user_email"] == "trader@test.local"
    assert item["tier"] == "50K"
    assert item["account_code"] == c["account_code"]
    assert item["amount"] == 2_400.0
    assert item["state"] == "requested"
    # Reviewer context: 50,000 start + 3,000 funded-stage realized − the
    # 2,400 request-time debit.
    assert item["starting_balance"] == 50_000.0
    assert item["balance"] == pytest.approx(50_600.0)
    assert item["total_approved_payouts"] == 0.0
    # PT-calendar-day metric: funded_at = _noon_on(6) is exactly 6 PT days
    # ago whatever the wall-clock hour (elapsed-24h .days would flip at
    # the funding hour and made this assertion time-of-day dependent).
    assert item["days_since_funded"] == 6

    # State filter + validation.
    assert admin_client.get(
        "/api/admin/payouts", params={"state": "approved"}
    ).json()["total"] == 0
    assert admin_client.get(
        "/api/admin/payouts", params={"state": "requested"}
    ).json()["total"] == 1
    assert (
        admin_client.get("/api/admin/payouts", params={"state": "bogus"})
        .status_code == 422
    )


def test_payout_decisions_via_api(admin_client, auth_client, monkeypatch):
    _no_pacing(monkeypatch)
    c = make_combine(auth_client, "50K")
    _fund_and_activate(auth_client, c["id"], total_profit=3_000.0)
    _request_payout(auth_client, c["id"])
    rid = admin_client.get("/api/admin/payouts").json()["items"][0]["id"]
    admin_id = _user_id(admin_client, "admin@test.local")

    # Deny REQUIRES a reason_code — the desk's 422 surfaces as-is.
    res = admin_client.post(f"/api/admin/payouts/{rid}/deny", json={"note": "n"})
    assert res.status_code == 422
    assert res.json()["detail"].startswith("unknown_reason_code:")

    res = admin_client.post(
        f"/api/admin/payouts/{rid}/deny",
        json={"reason_code": "rule_breach", "note": "News-window trades"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["state"] == "denied"
    assert res.json()["reason_code"] == "rule_breach"
    assert res.json()["reviewer_id"] == admin_id
    # The denial re-credit landed on the ledger.
    (ev,) = _events_of(admin_client, c["id"], "payout_denied")
    assert float(ev.amount) == 2_400.0

    # The denial re-credited in full — request again, then walk
    # hold → resume → approve → mark-paid.
    _request_payout(auth_client, c["id"])
    rid2 = admin_client.get("/api/admin/payouts").json()["items"][0]["id"]
    assert rid2 != rid
    res = admin_client.post(
        f"/api/admin/payouts/{rid2}/hold", json={"note": "checking"}
    )
    assert res.status_code == 200 and res.json()["state"] == "held"
    res = admin_client.post(f"/api/admin/payouts/{rid2}/resume")
    assert res.status_code == 200 and res.json()["state"] == "under_review"
    res = admin_client.post(f"/api/admin/payouts/{rid2}/approve")
    assert res.status_code == 200 and res.json()["state"] == "approved"
    res = admin_client.post(f"/api/admin/payouts/{rid2}/mark-paid")
    assert res.status_code == 200 and res.json()["state"] == "paid"

    # Illegal transition 409s surface as-is; unknown decision → 422;
    # missing request → the desk's 404.
    assert admin_client.post(f"/api/admin/payouts/{rid2}/approve").status_code == 409
    assert admin_client.post(f"/api/admin/payouts/{rid2}/shred").status_code == 422
    assert admin_client.post("/api/admin/payouts/999999/approve").status_code == 404

    # An audit row per successful mutation, none for the refused ones.
    for action, n in (
        ("payout.deny", 1), ("payout.hold", 1), ("payout.resume_review", 1),
        ("payout.approve", 1), ("payout.mark_paid", 1),
    ):
        rows = _actions(admin_client, action)
        assert len(rows) == n, action
        assert rows[0].actor_id == admin_id
        assert rows[0].target_type == "payout_request"

    # The paid request now shows in the user's approved-to-date context and
    # the queue is empty again.
    assert admin_client.get("/api/admin/payouts").json()["total"] == 0
    assert admin_client.get(
        "/api/admin/payouts", params={"state": "paid"}
    ).json()["items"][0]["total_approved_payouts"] == 2_400.0


# ---------------------------------------------------------------------------
# Platform kill switch
# ---------------------------------------------------------------------------


def test_platform_get_shape(admin_client):
    res = admin_client.get("/api/admin/platform")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "trading_mode": "normal",
        "banned_symbols": [],
        "zero_dte_universe": ["SPY", "QQQ", "IWM"],
        "enforce_tradeable_universe": True,
    }


def test_platform_put_flips_the_live_gate(admin_client, auth_client, monkeypatch):
    """The kill switch must bind on the REAL open path immediately: a PUT
    banning a symbol 422s the very next open; halting 503s it. Market data
    is stubbed (test_risk_controls pattern) — the gate itself reads no
    market data, so it works when the feed is down."""
    make_combine(auth_client, "50K")
    _stub_market(monkeypatch)
    assert _open_leg(auth_client).status_code == 201  # baseline: SPY opens

    res = admin_client.put(
        "/api/admin/platform", json={"banned_symbols": ["spy"]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["banned_symbols"] == ["SPY"]  # normalized
    blocked = _open_leg(auth_client)
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["detail"].startswith("symbol_not_tradeable: SPY")

    res = admin_client.put("/api/admin/platform", json={"trading_mode": "halted"})
    assert res.status_code == 200 and res.json()["trading_mode"] == "halted"
    blocked = _open_leg(auth_client, symbol="QQQ")
    assert blocked.status_code == 503
    assert blocked.json()["detail"].startswith("trading_halted:")

    # Flip everything back — trading resumes.
    res = admin_client.put(
        "/api/admin/platform",
        json={"trading_mode": "normal", "banned_symbols": []},
    )
    assert res.status_code == 200
    assert _open_leg(auth_client).status_code == 201

    # Validation: unknown mode → 422, empty body → 400.
    assert (
        admin_client.put(
            "/api/admin/platform", json={"trading_mode": "panic"}
        ).status_code == 422
    )
    assert admin_client.put("/api/admin/platform", json={}).status_code == 400

    updates = _actions(admin_client, "platform.update")
    assert len(updates) == 3
    assert '"trading_mode": "normal"' in updates[0].before_json
    assert '"SPY"' in updates[0].after_json
    assert '"trading_mode": "halted"' in updates[1].after_json


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_metrics_shape_with_seeded_data(admin_client, auth_client):
    c1 = make_combine(auth_client, "50K")
    make_combine(auth_client, "100K")
    _fund_and_activate(auth_client, c1["id"], total_profit=3_000.0)
    _request_payout(auth_client, c1["id"])  # 2,400 pending liability
    res = auth_client.post(
        "/api/support/tickets",
        json={"category": "payout", "subject": "s", "body": "b"},
    )
    assert res.status_code == 201

    res = admin_client.get("/api/admin/metrics")
    assert res.status_code == 200, res.text
    m = res.json()

    assert m["mrr"] == pytest.approx(
        monthly_price("50K") + monthly_price("100K")
    )
    assert m["combines"]["50K"]["by_status"] == {"active": 1}
    assert m["combines"]["50K"]["by_outcome"] == {"passed": 1}
    assert m["combines"]["100K"]["by_outcome"] == {"active": 1}
    assert m["pass_rate"]["50K"] == 1.0     # 1 funded, 0 failed
    assert m["pass_rate"]["100K"] is None   # no terminal outcome yet
    assert m["payout_liability"] == {
        "requested_pending": 2_400.0, "approved_unpaid": 0.0,
    }
    assert m["users_total"] == 2
    assert m["users_last_30d"] == 2
    assert m["tickets_open"] == 1


# ---------------------------------------------------------------------------
# Jobs health
# ---------------------------------------------------------------------------


def test_jobs_health_after_run_logged(admin_client, session_factory, monkeypatch):
    # run_logged records through database.SessionLocal (its own session, by
    # design); point it at the test database.
    monkeypatch.setattr("database.SessionLocal", session_factory)

    assert run_logged("noop_job", lambda: 42)() == 42
    with pytest.raises(ValueError):
        run_logged("boom_job", lambda: (_ for _ in ()).throw(ValueError("kaput")))()
    # A stale money-critical job: a run 10
    # minutes old is > 3 cadences behind.
    session = session_factory()
    session.add(
        JobRun(
            name="monitor_orders", status="ok", duration_s=0.1,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
    )
    session.commit()
    session.close()

    res = admin_client.get("/api/admin/jobs")
    assert res.status_code == 200, res.text
    by_name = {j["name"]: j for j in res.json()}
    assert set(by_name) == {"noop_job", "boom_job", "monitor_orders"}

    noop = by_name["noop_job"]
    assert noop["status"] == "ok"
    assert noop["error"] is None
    assert noop["cadence_s"] is None and noop["stale"] is False

    boom = by_name["boom_job"]
    assert boom["status"] == "error"
    assert "kaput" in boom["error"]

    monitor = by_name["monitor_orders"]
    # Cadence tracks config.order_monitor_interval_s (default 5s since the
    # audit-wave-3 tightening); 10 minutes behind is stale at any setting.
    assert monitor["cadence_s"] == max(1, int(settings.order_monitor_interval_s))
    assert monitor["stale"] is True


# ---------------------------------------------------------------------------
# Audit trail endpoint
# ---------------------------------------------------------------------------


def test_actions_log_filters_and_pagination(admin_client, auth_client):
    uid = _user_id(admin_client, "trader@test.local")
    admin_client.post(f"/api/admin/users/{uid}/suspend", json={"reason": "r1"})
    admin_client.post(f"/api/admin/users/{uid}/unsuspend", json={})
    admin_client.post(
        f"/api/admin/users/{uid}/grant-reset-credit", json={"reason": "r2"}
    )
    admin_client.put("/api/admin/platform", json={"trading_mode": "close_only"})

    res = admin_client.get("/api/admin/actions")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 4 and body["page"] == 1
    # Newest first, before/after round-trip as parsed dicts.
    assert [a["action"] for a in body["items"]] == [
        "platform.update", "user.grant_reset_credit",
        "user.unsuspend", "user.suspend",
    ]
    suspend = body["items"][3]
    assert suspend["before"] == {"suspended_at": None}
    assert suspend["after"]["suspended_at"] is not None
    assert suspend["reason"] == "r1"

    # Pagination.
    page1 = admin_client.get(
        "/api/admin/actions", params={"page": 1, "page_size": 3}
    ).json()
    page2 = admin_client.get(
        "/api/admin/actions", params={"page": 2, "page_size": 3}
    ).json()
    assert len(page1["items"]) == 3 and len(page2["items"]) == 1
    assert page1["total"] == page2["total"] == 4
    assert page2["items"][0]["action"] == "user.suspend"

    # Target filters — how a specific user's dispute gets answered.
    scoped = admin_client.get(
        "/api/admin/actions", params={"target_type": "user", "target_id": uid}
    ).json()
    assert scoped["total"] == 3
    assert all(a["target_type"] == "user" and a["target_id"] == uid
               for a in scoped["items"])
    assert admin_client.get(
        "/api/admin/actions", params={"target_type": "payment"}
    ).json()["total"] == 0


# ---------------------------------------------------------------------------
# Review-wave regressions (2026-07-15): unfail guards
# ---------------------------------------------------------------------------


def test_unfail_refuses_archived_combine(admin_client, auth_client):
    """Unfail must never resurrect an archived (refunded / ended) combine."""
    c = make_combine(auth_client, "50K")
    session = _session(admin_client)
    combine = session.get(Combine, c["id"])
    combine.outcome = "failed"
    combine.status = "archived"
    session.add(combine)
    session.commit()
    session.close()

    res = admin_client.post(
        f"/api/admin/combines/{c['id']}/adjust",
        json={"action": "unfail", "reason": "please"},
    )
    assert res.status_code == 409
    assert "combine_archived" in res.json()["detail"]
    session = _session(admin_client)
    assert session.get(Combine, c["id"]).status == "archived"
    session.close()


def test_unfail_still_breached_surfaces_engine_refail(admin_client, auth_client):
    """When the balance still sits through the MLL floor, the engine re-fails
    the combine on the very next read — the endpoint runs that read NOW and
    409s so the operator decision isn't silently discarded 5 minutes later."""
    c = make_combine(auth_client, "50K")
    # Bury the balance: -$5,000 realized on a 50K (MLL trail is far smaller),
    # then persist the engine's failed outcome by reading a snapshot.
    session = _session(admin_client)
    _seed_closed(
        session, c["id"], -5_000.0, datetime.now(timezone.utc) - timedelta(days=1)
    )
    session.commit()
    combine = session.get(Combine, c["id"])
    from services.combine_state import combine_snapshot

    snap = combine_snapshot(session, combine)
    assert snap.outcome == "failed"  # engine failed it on the read
    session.close()

    res = admin_client.post(
        f"/api/admin/combines/{c['id']}/adjust",
        json={"action": "unfail", "reason": "clemency"},
    )
    assert res.status_code == 409
    assert "still_breached" in res.json()["detail"]
    # The combine ends failed (engine re-verdict), with both the unfail and
    # the re-fail honestly recorded.
    session = _session(admin_client)
    assert session.get(Combine, c["id"]).outcome == "failed"
    session.close()
    assert len(_events_of(admin_client, c["id"], "unfailed")) == 1
