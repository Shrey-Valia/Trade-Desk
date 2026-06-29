"""Cookie / session config (WS7).

Two config knobs were added:
  - cookie_secure is now ENV-DRIVEN and prod-safe by default: an explicit
    COOKIE_SECURE wins, else it follows app_env (Secure in production, open in
    development). Resolved by the Settings.cookie_secure property.
  - the session TTL is configurable via session_ttl_days (default shortened
    30 → 14), driving both the auth_sessions row expiry and the cookie Max-Age.

These tests drive the real signup endpoint and inspect the Set-Cookie header +
the persisted session row. cookie_secure is a property, so tests set the
underlying `cookie_secure_override` / `app_env` fields (not the property).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from config import Settings, settings
from models.auth_session import AuthSession

# --- cookie_secure resolution (pure config) --------------------------------


def test_cookie_secure_defaults_open_in_development():
    s = Settings(app_env="development")
    assert s.is_production is False
    assert s.cookie_secure is False


def test_cookie_secure_defaults_secure_in_production():
    s = Settings(app_env="production")
    assert s.is_production is True
    assert s.cookie_secure is True


def test_explicit_cookie_secure_override_wins_either_way():
    # Force OFF in prod (e.g. behind a TLS-terminating proxy that handles it).
    assert Settings(app_env="production", cookie_secure=False).cookie_secure is False
    # Force ON in dev.
    assert Settings(app_env="development", cookie_secure=True).cookie_secure is True


def test_session_ttl_default_is_fourteen_days():
    s = Settings()
    assert s.session_ttl_days == 14
    assert s.session_ttl.days == 14


def test_session_ttl_is_configurable():
    assert Settings(session_ttl_days=3).session_ttl.days == 3


# --- cookie header reflects the config (live endpoint) ---------------------


def _signup(client, email="cfg@test.local"):
    return client.post(
        "/api/auth/signup", json={"email": email, "password": "password123"}
    )


def test_secure_flag_present_when_cookie_secure_on(client, monkeypatch):
    # cookie_secure is a property → set the underlying override field.
    monkeypatch.setattr(settings, "cookie_secure_override", True, raising=False)
    res = _signup(client)
    assert res.status_code == 201
    set_cookie = res.headers.get("set-cookie", "")
    assert "td_session=" in set_cookie
    assert "Secure" in set_cookie


def test_secure_flag_absent_when_cookie_secure_off(client, monkeypatch):
    monkeypatch.setattr(settings, "cookie_secure_override", False, raising=False)
    res = _signup(client, "cfg2@test.local")
    assert res.status_code == 201
    set_cookie = res.headers.get("set-cookie", "")
    # Starlette only emits "Secure" when secure=True.
    assert "Secure" not in set_cookie


def test_cookie_max_age_follows_session_ttl(client, monkeypatch):
    monkeypatch.setattr(settings, "session_ttl_days", 2, raising=False)
    res = _signup(client, "ttl@test.local")
    assert res.status_code == 201
    set_cookie = res.headers.get("set-cookie", "").lower()
    assert "max-age=172800" in set_cookie  # 2 days in seconds


def test_session_row_expiry_follows_session_ttl(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "session_ttl_days", 5, raising=False)
    assert _signup(client, "rowttl@test.local").status_code == 201
    with session_factory() as s:
        row = s.execute(select(AuthSession)).scalars().one()
        delta = row.expires_at - datetime.now(UTC)
        # ~5 days out (allow generous slack for clock + test latency).
        assert 4.9 < delta.total_seconds() / 86400 < 5.1
