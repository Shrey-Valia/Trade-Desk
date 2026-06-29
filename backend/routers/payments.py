"""Payments — Stripe Checkout + webhook fulfilment (OPT-IN).

When Stripe is NOT configured every endpoint degrades gracefully: /config
reports `stripe_enabled: false` and /checkout returns `mode: "placeholder"`
so the frontend falls back to the free `POST /api/combines/purchase` flow.

When Stripe IS configured:
  - POST /checkout creates a pending Payment + a Stripe Checkout Session and
    returns its URL; the browser redirects there to pay.
  - POST /webhook (called by Stripe, unauthenticated but signature-verified)
    fulfils `checkout.session.completed` by marking the Payment paid and
    provisioning the combine via the shared provision_combine helper — the
    same code path the placeholder purchase uses.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_session
from models.payment import Payment
from models.user import User
from services import payments
from services.auth import get_current_user
from services.combine_provision import assert_slot_available, provision_combine
from services.rate_limit import enforce_user, financial_limiter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["payments"])


class PaymentsConfigOut(BaseModel):
    stripe_enabled: bool
    # Per-tier purchasability (a Price ID is configured). Empty/all-false
    # when Stripe is off — the frontend then uses the placeholder flow.
    tiers: dict[str, bool]


class CheckoutIn(BaseModel):
    tier: Literal["50K", "100K", "150K"]
    name: str | None = Field(default=None, min_length=1, max_length=64)


class CheckoutOut(BaseModel):
    # "stripe" → redirect the browser to checkout_url.
    # "placeholder" → Stripe is off; call /api/combines/purchase instead.
    mode: Literal["stripe", "placeholder"]
    checkout_url: str | None = None


@router.get("/config", response_model=PaymentsConfigOut)
def payments_config() -> PaymentsConfigOut:
    """Public: lets the frontend decide whether to show a real checkout or
    the free placeholder purchase button."""
    enabled = payments.stripe_enabled()
    return PaymentsConfigOut(
        stripe_enabled=enabled,
        tiers=payments.purchasable_tiers() if enabled else {},
    )


@router.post("/checkout", response_model=CheckoutOut)
def create_checkout(
    payload: CheckoutIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CheckoutOut:
    # Per-user throttle — same budget/scope as the placeholder purchase path it
    # mirrors, so the limit holds however the user buys (checkout writes a
    # pending Payment + creates a Stripe session). Applied before the Stripe-off
    # short-circuit so the limit is consistent regardless of configuration.
    if not payments.stripe_enabled():
        # Stripe off → tell the frontend to use the free flow. Don't consume a
        # 'purchase' rate-limit hit here: this is just a config probe, and the
        # real buy goes through /purchase (which has its own 'purchase' hit) —
        # charging both would halve the effective purchase budget.
        return CheckoutOut(mode="placeholder")
    enforce_user(financial_limiter, user.id, "purchase")

    price_id = payments.price_id_for(payload.tier)
    if not price_id:
        raise HTTPException(503, f"pricing not configured for the {payload.tier} tier")

    # Fail fast if the user is already at the combine cap, before sending
    # them to pay for something we can't provision.
    assert_slot_available(session, user)

    # Pending payment row; the webhook flips it to paid + sets the amount.
    payment = Payment(
        user_id=user.id,
        tier=payload.tier,
        amount=None,
        status="pending",
    )
    session.add(payment)
    session.commit()
    session.refresh(payment)

    try:
        checkout = payments.create_checkout_session(
            user_id=user.id,
            tier=payload.tier,
            price_id=price_id,
            payment_id=payment.id,
            combine_name=payload.name,
        )
    except Exception as exc:  # noqa: BLE001
        payment.status = "failed"
        session.commit()
        log.exception("stripe checkout creation failed")
        raise HTTPException(502, "could not start checkout") from exc

    return CheckoutOut(mode="stripe", checkout_url=checkout.url)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """Stripe → us. Unauthenticated but signature-verified. Idempotent:
    a Payment already marked paid is a no-op (Stripe retries events)."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = payments.verify_webhook_event(payload, sig)
    except ValueError as exc:
        raise HTTPException(400, "invalid signature") from exc

    if event.get("type") != "checkout.session.completed":
        # We only fulfil completed checkouts; ack everything else so Stripe
        # stops resending.
        return {"received": True, "handled": False}

    obj = (event.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    payment_id = metadata.get("payment_id")
    if not payment_id:
        log.warning("checkout.session.completed without payment_id metadata")
        return {"received": True, "handled": False}

    payment = session.get(Payment, int(payment_id))
    if payment is None:
        log.warning("webhook references unknown payment_id=%s", payment_id)
        return {"received": True, "handled": False}
    if payment.status == "paid":
        return {"received": True, "handled": True}  # already fulfilled

    # Amount is read back from Stripe (cents → dollars) — never invented.
    amount_total = obj.get("amount_total")
    if amount_total is not None:
        payment.amount = float(amount_total) / 100.0
    payment.status = "paid"

    user = session.get(User, payment.user_id)
    if user is None:
        session.commit()
        log.error("paid payment %s has no user %s", payment.id, payment.user_id)
        return {"received": True, "handled": False}

    try:
        provision_combine(
            session,
            user,
            tier_key=payment.tier,
            name=metadata.get("combine_name") or None,
            payment=payment,
        )
    except HTTPException:
        # E.g. the slot cap filled between checkout and fulfilment. Keep the
        # payment marked paid for manual resolution; ack so Stripe stops.
        session.commit()
        log.exception("could not provision combine for paid payment %s", payment.id)
        return {"received": True, "handled": False}

    session.commit()
    return {"received": True, "handled": True}
