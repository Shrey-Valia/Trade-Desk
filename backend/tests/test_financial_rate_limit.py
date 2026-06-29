"""Per-user rate limits on the financial endpoints (WS7).

Payout request, account activation, and combine purchase / Stripe checkout are
authenticated money actions, so they're throttled per USER (user_id + scope) via
`enforce_user(financial_limiter, ...)` — not per IP. Each test drops the
limiter's budget low with monkeypatch (mirroring the auth-limiter tests) and
asserts the Nth rapid call returns 429 with a Retry-After header.

The financial_limiter is process-global and reset between tests by the autouse
fixture in conftest, so budgets don't bleed across cases.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from config import settings
from models.user import User
from services import payments
from services.rate_limit import financial_limiter
from tests.conftest import make_combine


def _user_id(session_factory, email="trader@test.local") -> int:
    with session_factory() as s:
        return s.execute(select(User.id).where(User.email == email)).scalar_one()


# --- purchase (combines.py) ------------------------------------------------


def test_purchase_throttled_returns_429(auth_client, monkeypatch):
    """The Nth rapid purchase from one user is a 429 with Retry-After; the
    calls under the budget all succeed (201)."""
    monkeypatch.setattr(financial_limiter, "max_attempts", 2)
    body = {"tier": "50K"}
    assert auth_client.post("/api/combines/purchase", json=body).status_code == 201
    assert auth_client.post("/api/combines/purchase", json=body).status_code == 201
    res = auth_client.post("/api/combines/purchase", json=body)  # 3rd → blocked
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_purchase_throttle_is_per_user(auth_client, second_user_client, monkeypatch):
    """One user exhausting the purchase budget does NOT block a different user —
    the key is user_id, not the shared TestClient host/IP."""
    monkeypatch.setattr(financial_limiter, "max_attempts", 1)
    # First user burns their single allowed purchase, then 429s.
    assert auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code == 201
    assert auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code == 429
    # A different user still has their own untouched budget.
    assert (
        second_user_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code
        == 201
    )


def test_purchase_throttle_disabled_when_attempts_non_positive(auth_client, monkeypatch):
    """attempts <= 0 disables the financial throttle — many rapid purchases,
    never a 429. (A 409 once the MAX_COMBINES slot cap fills is fine and
    expected; the point is the LIMITER never fires.)"""
    monkeypatch.setattr(financial_limiter, "max_attempts", 0)
    assert not financial_limiter.enabled
    for _ in range(8):
        assert (
            auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code
            != 429
        )


# --- activation (combines.py) ----------------------------------------------


def test_activation_throttled_returns_429(auth_client, monkeypatch):
    """Activation is throttled per user. The combine here isn't funded, so the
    endpoint 409s on the merits — but the throttle fires FIRST once the budget
    is spent, proving the limit wraps the handler."""
    monkeypatch.setattr(financial_limiter, "max_attempts", 2)
    c = make_combine(auth_client, "50K")
    path = f"/api/combines/{c['id']}/activate-account"
    # Not funded → 409 on the merits, but the throttle still counts the hit.
    assert auth_client.post(path).status_code == 409
    assert auth_client.post(path).status_code == 409
    res = auth_client.post(path)  # 3rd → throttled before the 409
    assert res.status_code == 429
    assert "Retry-After" in res.headers


# --- payout (combines.py) --------------------------------------------------


def test_payout_throttled_returns_429(auth_client, monkeypatch):
    """Payout is throttled per user across ALL combines (the scope is just
    'payout', not per-combine). An unfunded combine 409s on the merits, but the
    Nth rapid call is pre-empted with a 429."""
    monkeypatch.setattr(financial_limiter, "max_attempts", 2)
    c = make_combine(auth_client, "50K")
    path = f"/api/combines/{c['id']}/payout"
    assert auth_client.post(path).status_code == 409  # not funded
    assert auth_client.post(path).status_code == 409
    res = auth_client.post(path)  # 3rd → throttled
    assert res.status_code == 429
    assert "Retry-After" in res.headers


# --- Stripe checkout (payments.py) -----------------------------------------


@pytest.fixture
def stripe_on(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_x", raising=False)
    monkeypatch.setattr(settings, "stripe_price_50k", "price_50k", raising=False)


def test_checkout_throttled_returns_429(auth_client, stripe_on, monkeypatch):
    """Stripe checkout shares the 'purchase' scope with the placeholder buy
    flow, so the per-user limit holds however the user buys."""
    monkeypatch.setattr(financial_limiter, "max_attempts", 2)

    def fake_create(**kwargs):
        return payments.CheckoutSession(url="https://stripe.test/cs", session_id="cs")

    monkeypatch.setattr(payments, "_create_checkout_session", fake_create)

    body = {"tier": "50K"}
    assert auth_client.post("/api/payments/checkout", json=body).status_code == 200
    assert auth_client.post("/api/payments/checkout", json=body).status_code == 200
    res = auth_client.post("/api/payments/checkout", json=body)  # 3rd → blocked
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_checkout_and_purchase_share_one_budget(auth_client, monkeypatch):
    """Checkout (Stripe off → placeholder) and the placeholder purchase both
    consume the same 'purchase' scope, so they can't be used to double the
    effective budget."""
    monkeypatch.setattr(financial_limiter, "max_attempts", 2)
    # One placeholder checkout call (Stripe off → 200 placeholder, counts a hit).
    assert auth_client.post("/api/payments/checkout", json={"tier": "50K"}).status_code == 200
    # One real purchase (counts the 2nd hit on the shared scope).
    assert auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code == 201
    # Budget of 2 is now spent → the next purchase is throttled.
    assert auth_client.post("/api/combines/purchase", json={"tier": "50K"}).status_code == 429
