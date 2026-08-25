"""Admin-minted password-reset links.

Closes the recovery gap that exists while MAIL_PROVIDER=console: a
locked-out invitee could only be helped by grepping the reset token out of
the server log.

The design decision under test is that the endpoint mints a LINK and never
sets a password. An operator who knows a trader's password can open
positions and request payouts as them, which destroys non-repudiation on a
platform that moves money and makes the audit log unfalsifiable. So the
tests below assert what the operator does NOT get as carefully as what they
do.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from config import settings
from main import app
from models.admin_action import AdminAction
from models.notification import EmailOutbox
from models.password_reset import PasswordResetToken
from models.user import User
from tests.conftest import _signup

_PW = "password123"


@pytest.fixture
def admin_client(api_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", ("admin@test.local",))
    c = TestClient(app)
    _signup(c, "admin@test.local")
    return c


@pytest.fixture
def target(api_client, session_factory):
    """A separate trader to act on."""
    _signup(api_client, "locked@test.local")
    s = session_factory()
    user = s.execute(
        select(User).where(User.email == "locked@test.local")
    ).scalar_one()
    uid = user.id
    s.close()
    return uid


def _mint(admin_client, uid: int, **body):
    return admin_client.post(f"/api/admin/users/{uid}/password-reset", json=body)


# -- the link works end to end ---------------------------------------------


def test_minted_link_resets_the_password(admin_client, api_client, target):
    res = _mint(admin_client, target)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["email"] == "locked@test.local"
    assert body["emailed"] is True

    token = parse_qs(urlparse(body["reset_url"]).query)["token"][0]

    # The trader completes it themselves — the operator never sets a password.
    done = api_client.post(
        "/api/auth/reset", json={"token": token, "new_password": "brand-new-pw-1"}
    )
    assert done.status_code == 204, done.text

    # And the new password actually works.
    signin = api_client.post(
        "/api/auth/signin",
        json={"email": "locked@test.local", "password": "brand-new-pw-1"},
    )
    assert signin.status_code == 200
    # While the old one does not.
    assert (
        api_client.post(
            "/api/auth/signin",
            json={"email": "locked@test.local", "password": _PW},
        ).status_code
        == 401
    )


def test_link_is_single_use(admin_client, api_client, target):
    token = parse_qs(
        urlparse(_mint(admin_client, target).json()["reset_url"]).query
    )["token"][0]
    first = api_client.post(
        "/api/auth/reset", json={"token": token, "new_password": "first-pw-123"}
    )
    assert first.status_code == 204
    second = api_client.post(
        "/api/auth/reset", json={"token": token, "new_password": "second-pw-123"}
    )
    assert second.status_code == 400


def test_minting_again_invalidates_the_previous_link(
    admin_client, api_client, target
):
    """At most one live link per account — a stale link left working is a
    credential the operator has lost track of."""
    old = parse_qs(
        urlparse(_mint(admin_client, target).json()["reset_url"]).query
    )["token"][0]
    new = parse_qs(
        urlparse(_mint(admin_client, target).json()["reset_url"]).query
    )["token"][0]
    assert old != new

    assert (
        api_client.post(
            "/api/auth/reset", json={"token": old, "new_password": "nope-pw-123"}
        ).status_code
        == 400
    )
    assert (
        api_client.post(
            "/api/auth/reset", json={"token": new, "new_password": "yes-pw-1234"}
        ).status_code
        == 204
    )


# -- what the operator must NOT get ----------------------------------------


def test_raw_token_is_never_stored(admin_client, target, session_factory):
    """Only the sha256 is at rest — same custody as sessions."""
    url = _mint(admin_client, target).json()["reset_url"]
    token = parse_qs(urlparse(url).query)["token"][0]

    s = session_factory()
    rows = s.execute(select(PasswordResetToken)).scalars().all()
    assert len(rows) == 1
    assert rows[0].token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in rows[0].token_hash
    s.close()


def test_token_never_reaches_the_audit_log(admin_client, target, session_factory):
    """An audit row is long-lived and widely readable. Logging the raw token
    beside a hashed column would defeat the point of hashing it."""
    url = _mint(admin_client, target, reason="user lost mailbox").json()["reset_url"]
    token = parse_qs(urlparse(url).query)["token"][0]

    s = session_factory()
    row = s.execute(
        select(AdminAction).where(AdminAction.action == "user.password_reset")
    ).scalar_one()
    assert token not in row.after_json
    assert token not in row.before_json
    assert token not in (row.reason or "")
    assert row.target_id == target
    assert row.reason == "user lost mailbox"
    # It should still record THAT a link was minted, and until when.
    assert "reset_link_minted" in row.after_json
    s.close()


def test_response_does_not_leak_a_password_or_hash(admin_client, target):
    body = _mint(admin_client, target).json()
    assert set(body) == {"user_id", "email", "reset_url", "expires_at", "emailed"}
    assert "password" not in str(body).lower().replace("reset-password", "")


# -- side effects ----------------------------------------------------------


def test_a_copy_is_queued_to_the_user(admin_client, target, session_factory):
    """Useful the moment SMTP is real, and a harmless no-op before that."""
    _mint(admin_client, target)
    s = session_factory()
    row = s.execute(
        select(EmailOutbox).where(EmailOutbox.template == "password_reset")
    ).scalar_one()
    assert row.to_email == "locked@test.local"
    assert "/reset-password?token=" in row.body
    s.close()


def test_minting_does_not_sign_the_user_out(admin_client, api_client, target):
    """Preparing a recovery link must not kick a working session — that would
    be a surprise. Suspension is the tool that blocks access."""
    # api_client's cookie jar holds the target's live session.
    assert api_client.get("/api/auth/me").status_code == 200
    _mint(admin_client, target)
    assert api_client.get("/api/auth/me").status_code == 200


def test_completing_the_reset_revokes_sessions(admin_client, api_client, target):
    """Once the password changes, every existing session must die — the
    reset exists because access may be compromised."""
    token = parse_qs(
        urlparse(_mint(admin_client, target).json()["reset_url"]).query
    )["token"][0]
    fresh = TestClient(app)
    fresh.post(
        "/api/auth/reset", json={"token": token, "new_password": "rotated-pw-99"}
    )
    assert api_client.get("/api/auth/me").status_code == 401


def test_expiry_follows_the_configured_ttl(admin_client, target, monkeypatch):
    monkeypatch.setattr(settings, "password_reset_ttl_h", 3.0)
    body = _mint(admin_client, target).json()
    expires = datetime.fromisoformat(body["expires_at"])
    delta = expires - datetime.now(UTC)
    assert timedelta(hours=2, minutes=45) < delta < timedelta(hours=3, minutes=15)


def test_link_uses_the_configured_frontend_origin(admin_client, target, monkeypatch):
    """A wrong FRONTEND_BASE_URL sends the trader to a dead host."""
    monkeypatch.setattr(settings, "frontend_base_url", "https://app.example.org")
    url = _mint(admin_client, target).json()["reset_url"]
    assert url.startswith("https://app.example.org/reset-password?token=")


# -- authz -----------------------------------------------------------------


def test_endpoint_is_admin_only(auth_client, target):
    assert (
        auth_client.post(f"/api/admin/users/{target}/password-reset").status_code
        == 403
    )


def test_unknown_user_404s(admin_client):
    assert _mint(admin_client, 999999).status_code == 404
