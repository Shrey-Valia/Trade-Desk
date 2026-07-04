"""Auth flow — signup/signin/signout/me, cookie semantics, gating."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config import settings
from models.auth_session import AuthSession


def test_signup_me_roundtrip(client):
    res = client.post(
        "/api/auth/signup",
        json={"email": "Alice@Test.Local ", "password": "password123"},
    )
    assert res.status_code == 201
    body = res.json()
    # Email normalized lowercase + stripped.
    assert body["email"] == "alice@test.local"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "alice@test.local"


def test_signup_sets_httponly_lax_cookie(client):
    res = client.post(
        "/api/auth/signup",
        json={"email": "cookie@test.local", "password": "password123"},
    )
    set_cookie = res.headers.get("set-cookie", "")
    assert "td_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_duplicate_email_409(client):
    payload = {"email": "dup@test.local", "password": "password123"}
    assert client.post("/api/auth/signup", json=payload).status_code == 201
    assert client.post("/api/auth/signup", json=payload).status_code == 409


def test_signin_wrong_password_and_unknown_email_identical(client):
    client.post(
        "/api/auth/signup",
        json={"email": "real@test.local", "password": "password123"},
    )
    wrong = client.post(
        "/api/auth/signin",
        json={"email": "real@test.local", "password": "nope-nope-nope"},
    )
    unknown = client.post(
        "/api/auth/signin",
        json={"email": "ghost@test.local", "password": "password123"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_signin_then_me(client):
    client.post(
        "/api/auth/signup",
        json={"email": "back@test.local", "password": "password123"},
    )
    client.post("/api/auth/signout")
    assert client.get("/api/auth/me").status_code == 401
    res = client.post(
        "/api/auth/signin",
        json={"email": "back@test.local", "password": "password123"},
    )
    assert res.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_signout_revokes(auth_client):
    assert auth_client.get("/api/auth/me").status_code == 200
    assert auth_client.post("/api/auth/signout").status_code == 204
    assert auth_client.get("/api/auth/me").status_code == 401
    # Idempotent — second signout with no cookie still 204s.
    assert auth_client.post("/api/auth/signout").status_code == 204


def test_short_password_422(client):
    res = client.post(
        "/api/auth/signup",
        json={"email": "short@test.local", "password": "short"},
    )
    assert res.status_code == 422


def test_invalid_email_422(client):
    res = client.post(
        "/api/auth/signup",
        json={"email": "not-an-email", "password": "password123"},
    )
    assert res.status_code == 422


def test_expired_session_401(auth_client, session_factory):
    # Force-expire every session row, then hit an authed endpoint.
    with session_factory() as s:
        for row in s.query(AuthSession).all():
            row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    assert auth_client.get("/api/auth/me").status_code == 401
    # The expired row was lazily deleted.
    with session_factory() as s:
        assert s.query(AuthSession).count() == 0


# --- sliding sessions --------------------------------------------------------
#
# The 14-day TTL used to be fixed at signin, so an active daily trader was
# hard-logged-out mid-session on day 14. Now any authenticated request made
# past the HALFWAY point of the TTL extends the row to a full TTL again and
# refreshes the cookie Max-Age on the same response. Before halfway nothing
# is written (no per-request UPDATE churn), and revocation is unchanged.


def _set_session_expiry(session_factory, expires_at: datetime) -> None:
    with session_factory() as s:
        row = s.query(AuthSession).one()
        row.expires_at = expires_at
        s.commit()


def test_session_past_halfway_slides(auth_client, session_factory):
    ttl = settings.session_ttl
    # Remaining lifetime ttl/4 < ttl/2 → past the halfway point.
    _set_session_expiry(session_factory, datetime.now(timezone.utc) + ttl / 4)

    res = auth_client.get("/api/auth/me")
    assert res.status_code == 200

    with session_factory() as s:
        remaining = s.query(AuthSession).one().expires_at - datetime.now(timezone.utc)
    assert remaining > ttl * 0.9  # extended to ~a full TTL
    # The cookie Max-Age is refreshed on the SAME response (same raw token).
    set_cookie = res.headers.get("set-cookie", "").lower()
    assert "td_session=" in set_cookie
    assert f"max-age={int(ttl.total_seconds())}" in set_cookie


def test_session_before_halfway_does_not_slide(auth_client, session_factory):
    ttl = settings.session_ttl
    # Remaining lifetime 3/4 of the TTL > ttl/2 → before halfway: no write.
    target = datetime.now(timezone.utc) + ttl * 3 / 4
    _set_session_expiry(session_factory, target)

    res = auth_client.get("/api/auth/me")
    assert res.status_code == 200

    with session_factory() as s:
        row = s.query(AuthSession).one()
        assert abs((row.expires_at - target).total_seconds()) < 1
    assert "set-cookie" not in [k.lower() for k in res.headers]


def test_slid_session_is_still_revocable(auth_client, session_factory):
    # Sliding keeps the SAME token/row — signout revocation is unchanged.
    ttl = settings.session_ttl
    _set_session_expiry(session_factory, datetime.now(timezone.utc) + ttl / 4)
    assert auth_client.get("/api/auth/me").status_code == 200  # slides
    assert auth_client.post("/api/auth/signout").status_code == 204
    assert auth_client.get("/api/auth/me").status_code == 401
    with session_factory() as s:
        assert s.query(AuthSession).count() == 0
