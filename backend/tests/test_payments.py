"""Stripe opt-in payments: config gating, checkout, and webhook fulfilment.

No test touches real Stripe — the two SDK boundary functions
(`_create_checkout_session`, `verify_webhook_event`) are monkeypatched, and
Stripe is "enabled" by setting the config keys for the duration of a test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from config import settings
from models.combine import Combine
from models.payment import Payment
from models.user import User
from services import payments


@pytest.fixture
def stripe_on(monkeypatch):
    """Turn Stripe on with placeholder Price IDs for the duration of a test."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x", raising=False)
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_x", raising=False)
    monkeypatch.setattr(settings, "stripe_price_50k", "price_50k", raising=False)
    monkeypatch.setattr(settings, "stripe_price_100k", "price_100k", raising=False)
    # 150K deliberately left blank → not purchasable.
    monkeypatch.setattr(settings, "stripe_price_150k", "", raising=False)


def _user_id(session_factory, email="trader@test.local") -> int:
    with session_factory() as s:
        return s.execute(select(User.id).where(User.email == email)).scalar_one()


# --- config gating --------------------------------------------------------


def test_config_reports_disabled_by_default(api_client):
    res = api_client.get("/api/payments/config")
    assert res.status_code == 200
    body = res.json()
    assert body["stripe_enabled"] is False
    assert body["tiers"] == {}


def test_config_reports_enabled_with_per_tier_flags(api_client, stripe_on):
    body = api_client.get("/api/payments/config").json()
    assert body["stripe_enabled"] is True
    assert body["tiers"] == {"50K": True, "100K": True, "150K": False}


# --- checkout -------------------------------------------------------------


def test_checkout_falls_back_to_placeholder_when_disabled(auth_client):
    res = auth_client.post("/api/payments/checkout", json={"tier": "50K"})
    assert res.status_code == 200
    assert res.json() == {"mode": "placeholder", "checkout_url": None}


def test_checkout_creates_pending_payment_and_returns_url(
    auth_client, session_factory, stripe_on, monkeypatch
):
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return payments.CheckoutSession(url="https://stripe.test/cs_123", session_id="cs_123")

    monkeypatch.setattr(payments, "_create_checkout_session", fake_create)

    res = auth_client.post(
        "/api/payments/checkout", json={"tier": "50K", "name": "My Combine"}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "stripe"
    assert body["checkout_url"] == "https://stripe.test/cs_123"

    # A pending payment row was created (no combine yet — that's the webhook).
    with session_factory() as s:
        payment = s.execute(select(Payment)).scalars().one()
        assert payment.status == "pending"
        assert payment.amount is None
        assert payment.combine_id is None
        assert s.execute(select(Combine)).scalars().first() is None

    # The configured Price ID + provisioning metadata were forwarded.
    assert captured["price_id"] == "price_50k"
    assert captured["metadata"]["tier"] == "50K"
    assert captured["metadata"]["combine_name"] == "My Combine"


def test_checkout_503_when_tier_price_not_configured(auth_client, stripe_on):
    res = auth_client.post("/api/payments/checkout", json={"tier": "150K"})
    assert res.status_code == 503
    assert "pricing not configured" in res.json()["detail"]


def test_checkout_requires_auth(api_client, stripe_on):
    res = api_client.post("/api/payments/checkout", json={"tier": "50K"})
    assert res.status_code == 401


# --- webhook fulfilment ---------------------------------------------------


def _completed_event(payment_id: int, user_id: int, *, tier="50K", amount=14900, name=""):
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "amount_total": amount,
                "payment_status": "paid",
                "metadata": {
                    "payment_id": str(payment_id),
                    "user_id": str(user_id),
                    "tier": tier,
                    "combine_name": name,
                },
            }
        },
    }


def _seed_pending_payment(session_factory, user_id: int, tier="50K") -> int:
    with session_factory() as s:
        p = Payment(user_id=user_id, tier=tier, amount=None, status="pending")
        s.add(p)
        s.commit()
        return p.id


def test_webhook_marks_paid_and_provisions_combine(
    auth_client, session_factory, monkeypatch
):
    uid = _user_id(session_factory)
    pid = _seed_pending_payment(session_factory, uid)
    event = _completed_event(pid, uid, name="Webhook Combine")
    monkeypatch.setattr(payments, "verify_webhook_event", lambda payload, sig: event)

    res = auth_client.post(
        "/api/payments/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"}
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"received": True, "handled": True}

    with session_factory() as s:
        payment = s.get(Payment, pid)
        assert payment.status == "paid"
        assert payment.amount == pytest.approx(149.0)  # 14900 cents, read from Stripe
        assert payment.combine_id is not None
        combine = s.get(Combine, payment.combine_id)
        assert combine is not None
        assert combine.tier == "50K"
        assert combine.name == "Webhook Combine"
        assert combine.user_id == uid


def test_webhook_is_idempotent(auth_client, session_factory, monkeypatch):
    uid = _user_id(session_factory)
    pid = _seed_pending_payment(session_factory, uid)
    event = _completed_event(pid, uid)
    monkeypatch.setattr(payments, "verify_webhook_event", lambda payload, sig: event)

    h = {"stripe-signature": "x"}
    auth_client.post("/api/payments/webhook", content=b"{}", headers=h)
    auth_client.post("/api/payments/webhook", content=b"{}", headers=h)  # retry

    with session_factory() as s:
        combines = s.execute(
            select(Combine).where(Combine.user_id == uid)
        ).scalars().all()
        assert len(combines) == 1  # provisioned exactly once


def test_webhook_rejects_bad_signature(auth_client, monkeypatch):
    def boom(payload, sig):
        raise ValueError("bad sig")

    monkeypatch.setattr(payments, "verify_webhook_event", boom)
    res = auth_client.post(
        "/api/payments/webhook", content=b"{}", headers={"stripe-signature": "nope"}
    )
    assert res.status_code == 400


def test_webhook_ignores_unrelated_event(auth_client, monkeypatch):
    event = {"type": "payment_intent.created", "data": {"object": {}}}
    monkeypatch.setattr(payments, "verify_webhook_event", lambda payload, sig: event)
    res = auth_client.post(
        "/api/payments/webhook", content=b"{}", headers={"stripe-signature": "x"}
    )
    assert res.status_code == 200
    assert res.json()["handled"] is False
