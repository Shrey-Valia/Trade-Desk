"""Invite codes — the closed-launch signup gate (admin mint/list/revoke +
redemption at signup).

Covers: the gate itself (off by default, on refuses a codeless signup); the
full redemption path and its refusals (unknown / reused / revoked / expired
/ wrong-bound-email); the atomicity contract (a refused redemption leaves NO
user row behind); single-use enforcement; the derived-status filter on the
admin list; the audit rows both mutations must write; and the authz boundary
(the invite endpoints are admin-only).

Conventions: admin bootstrap via settings.admin_emails (the B1 pattern used
by test_admin), and settings flipped with monkeypatch so the suite's default
open-signup posture is restored per test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from config import settings
from main import app
from models.admin_action import AdminAction
from models.invite import Invite
from models.user import User
from services.invites import generate_code, invite_status
from tests.conftest import _signup

_PW = "password123"


@pytest.fixture
def admin_client(api_client, monkeypatch):
    """An authenticated ADMIN on the same database (see test_admin)."""
    monkeypatch.setattr(settings, "admin_emails", ("admin@test.local",))
    c = TestClient(app)
    _signup(c, "admin@test.local")
    return c


@pytest.fixture
def invite_only(monkeypatch):
    """Flip the deployment into the closed-launch posture."""
    monkeypatch.setattr(settings, "signup_require_invite", True)


@pytest.fixture
def db_session(session_factory):
    """Direct DB access on the SAME engine the clients use — for aging a
    code out and for asserting on rows the API doesn't expose."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _mint(admin_client, **body) -> dict:
    res = admin_client.post("/api/admin/invites", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def _try_signup(client, email: str, code: str | None = None):
    payload = {"email": email, "password": _PW}
    if code is not None:
        payload["invite_code"] = code
    return client.post("/api/auth/signup", json=payload)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_signup_open_by_default(api_client):
    """The default posture is UNCHANGED — no code, account created. The
    whole rest of the suite depends on this staying true."""
    assert _try_signup(api_client, "open@test.local").status_code == 201


def test_signup_policy_reflects_the_setting(api_client, monkeypatch):
    res = api_client.get("/api/auth/signup-policy")
    assert res.status_code == 200
    assert res.json() == {"require_invite": False}

    monkeypatch.setattr(settings, "signup_require_invite", True)
    assert api_client.get("/api/auth/signup-policy").json() == {
        "require_invite": True
    }


def test_invite_required_refuses_codeless_signup(api_client, invite_only, db_session):
    res = _try_signup(api_client, "nocode@test.local")
    assert res.status_code == 403
    assert res.json()["detail"].startswith("invite_required:")
    # And no account was created.
    assert _user_count(db_session, "nocode@test.local") == 0


def test_valid_code_admits_signup(api_client, admin_client, invite_only):
    inv = _mint(admin_client)
    res = _try_signup(api_client, "guest@test.local", inv["code"])
    assert res.status_code == 201, res.text
    assert res.json()["email"] == "guest@test.local"


def test_code_is_case_and_whitespace_insensitive(api_client, admin_client, invite_only):
    inv = _mint(admin_client)
    noisy = f"  {inv['code'].lower()}  "
    assert _try_signup(api_client, "sloppy@test.local", noisy).status_code == 201


# ---------------------------------------------------------------------------
# Redemption refusals
# ---------------------------------------------------------------------------


def test_unknown_code_refused(api_client, invite_only):
    res = _try_signup(api_client, "ghost@test.local", generate_code())
    assert res.status_code == 403
    assert res.json()["detail"].startswith("invalid_invite:")


def test_code_is_single_use(api_client, admin_client, second_user_client, invite_only):
    inv = _mint(admin_client)
    assert _try_signup(api_client, "first@test.local", inv["code"]).status_code == 201
    res = _try_signup(second_user_client, "second@test.local", inv["code"])
    assert res.status_code == 403
    assert res.json()["detail"].startswith("already_redeemed:")


def test_revoked_code_refused(api_client, admin_client, invite_only):
    inv = _mint(admin_client)
    assert (
        admin_client.post(f"/api/admin/invites/{inv['id']}/revoke").status_code == 200
    )
    res = _try_signup(api_client, "late@test.local", inv["code"])
    assert res.status_code == 403
    assert res.json()["detail"].startswith("revoked_invite:")


def test_expired_code_refused(api_client, admin_client, invite_only, db_session):
    inv = _mint(admin_client)
    row = db_session.get(Invite, inv["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    res = _try_signup(api_client, "stale@test.local", inv["code"])
    assert res.status_code == 403
    assert res.json()["detail"].startswith("expired_invite:")


def test_email_bound_code_refuses_a_different_address(
    api_client, admin_client, invite_only
):
    inv = _mint(admin_client, email="invited@test.local")
    res = _try_signup(api_client, "someone.else@test.local", inv["code"])
    assert res.status_code == 403
    detail = res.json()["detail"]
    assert detail.startswith("wrong_email:")
    # Must not echo the bound address back to an unauthenticated caller.
    assert "invited@test.local" not in detail

    assert (
        _try_signup(api_client, "invited@test.local", inv["code"]).status_code == 201
    )


def test_refused_redemption_leaves_no_user_behind(
    api_client, invite_only, db_session
):
    """The atomicity contract: signup flushes the user row BEFORE redeeming,
    so a refusal must roll that row back — otherwise a burned attempt would
    squat the email address with a 409 forever."""
    email = "rollback@test.local"
    assert _try_signup(api_client, email, generate_code()).status_code == 403
    assert _user_count(db_session, email) == 0


def test_code_supplied_while_gate_is_off_is_still_redeemed(api_client, admin_client):
    """Gate OFF, code supplied: it must be validated and consumed, not
    silently ignored — otherwise the ledger would show it unused forever."""
    inv = _mint(admin_client)
    assert _try_signup(api_client, "early@test.local", inv["code"]).status_code == 201

    listed = admin_client.get("/api/admin/invites").json()["invites"]
    row = next(i for i in listed if i["id"] == inv["id"])
    assert row["status"] == "redeemed"
    assert row["redeemed_by_email"] == "early@test.local"


def test_bad_code_while_gate_is_off_still_refuses(api_client):
    res = _try_signup(api_client, "typo@test.local", generate_code())
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Admin surface
# ---------------------------------------------------------------------------


def test_invite_endpoints_are_admin_only(auth_client):
    assert auth_client.get("/api/admin/invites").status_code == 403
    assert auth_client.post("/api/admin/invites", json={}).status_code == 403
    assert auth_client.post("/api/admin/invites/1/revoke").status_code == 403


def test_mint_shape_and_defaults(admin_client, monkeypatch):
    monkeypatch.setattr(settings, "invite_default_ttl_days", 7.0)
    inv = _mint(admin_client, note="  first trader  ")
    assert inv["code"].startswith("TD-")
    assert inv["status"] == "active"
    assert inv["email"] is None
    assert inv["note"] == "first trader"
    assert inv["created_by_email"] == "admin@test.local"
    assert inv["redeemed_at"] is None
    # Default TTL applied.
    expires = datetime.fromisoformat(inv["expires_at"])
    assert timedelta(days=6) < expires - datetime.now(timezone.utc) < timedelta(days=8)


def test_zero_ttl_means_never_expires(admin_client):
    assert _mint(admin_client, expires_in_days=0)["expires_at"] is None


def test_mint_refuses_an_email_that_already_has_an_account(admin_client, api_client):
    _signup(api_client, "taken@test.local")
    res = admin_client.post("/api/admin/invites", json={"email": "taken@test.local"})
    assert res.status_code == 409
    assert res.json()["detail"].startswith("already_registered:")


def test_mint_rejects_a_malformed_bound_email(admin_client):
    res = admin_client.post("/api/admin/invites", json={"email": "not-an-email"})
    assert res.status_code == 422


def test_list_filters_by_derived_status(admin_client, api_client, db_session):
    active = _mint(admin_client, note="active one")
    revoked = _mint(admin_client, note="revoked one")
    expired = _mint(admin_client, note="expired one")
    redeemed = _mint(admin_client, note="redeemed one")

    admin_client.post(f"/api/admin/invites/{revoked['id']}/revoke")
    row = db_session.get(Invite, expired["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    _try_signup(api_client, "redeemer@test.local", redeemed["code"])

    def ids(status: str) -> set[int]:
        res = admin_client.get(f"/api/admin/invites?status={status}")
        assert res.status_code == 200
        return {i["id"] for i in res.json()["invites"]}

    assert ids("active") == {active["id"]}
    assert ids("revoked") == {revoked["id"]}
    assert ids("expired") == {expired["id"]}
    assert ids("redeemed") == {redeemed["id"]}

    all_res = admin_client.get("/api/admin/invites").json()
    assert all_res["total"] == 4
    assert all_res["require_invite"] is False


def test_list_rejects_an_unknown_status(admin_client):
    res = admin_client.get("/api/admin/invites?status=pending")
    assert res.status_code == 422
    assert res.json()["detail"].startswith("invalid_status:")


def test_list_searches_code_email_and_note(admin_client):
    target = _mint(admin_client, email="needle@test.local", note="cohort b")
    _mint(admin_client, note="unrelated")

    for q in (target["code"], "needle", "cohort"):
        found = admin_client.get(f"/api/admin/invites?q={q}").json()["invites"]
        assert [i["id"] for i in found] == [target["id"]], q


def test_revoke_is_refused_once_redeemed(admin_client, api_client, invite_only):
    inv = _mint(admin_client)
    assert _try_signup(api_client, "used@test.local", inv["code"]).status_code == 201
    res = admin_client.post(f"/api/admin/invites/{inv['id']}/revoke")
    assert res.status_code == 409
    assert res.json()["detail"].startswith("already_redeemed:")


def test_double_revoke_is_refused(admin_client):
    inv = _mint(admin_client)
    assert (
        admin_client.post(f"/api/admin/invites/{inv['id']}/revoke").status_code == 200
    )
    res = admin_client.post(f"/api/admin/invites/{inv['id']}/revoke")
    assert res.status_code == 409
    assert res.json()["detail"].startswith("already_revoked:")


def test_revoke_404s_on_an_unknown_invite(admin_client):
    assert admin_client.post("/api/admin/invites/99999/revoke").status_code == 404


def test_both_mutations_write_audit_rows(admin_client, db_session):
    inv = _mint(admin_client, note="audited")
    admin_client.post(
        f"/api/admin/invites/{inv['id']}/revoke", json={"reason": "sent to the wrong person"}
    )
    actions = (
        db_session.execute(
            select(AdminAction)
            .where(AdminAction.target_type == "invite")
            .order_by(AdminAction.id)
        )
        .scalars()
        .all()
    )
    assert [a.action for a in actions] == ["invite.create", "invite.revoke"]
    assert all(a.target_id == inv["id"] for a in actions)
    assert actions[1].reason == "sent to the wrong person"


# ---------------------------------------------------------------------------
# Derived status unit coverage
# ---------------------------------------------------------------------------


def test_redeemed_outranks_expiry_and_revocation():
    """A used code reads 'redeemed' even if it later ages out or an admin
    tries to revoke it — 'this was used' is the fact an operator needs."""
    now = datetime.now(timezone.utc)
    inv = Invite(
        code="TD-XXXX-XXXX",
        created_by_id=1,
        created_at=now,
        expires_at=now - timedelta(days=1),
        redeemed_at=now,
        revoked_at=now,
    )
    assert invite_status(inv) == "redeemed"

    inv.redeemed_at = None
    assert invite_status(inv) == "revoked"

    inv.revoked_at = None
    assert invite_status(inv) == "expired"

    inv.expires_at = None
    assert invite_status(inv) == "active"


def test_generated_codes_avoid_ambiguous_characters():
    for _ in range(50):
        body = generate_code().removeprefix("TD-").replace("-", "")
        assert not (set(body) & set("01LIOSB8")), body


def _user_count(session, email: str) -> int:
    return len(session.execute(select(User.id).where(User.email == email)).all())
