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
    same code path the placeholder purchase uses. It also closes the
    lifecycle loop: `checkout.session.expired` fails an abandoned pending
    payment, and `charge.refunded` / `charge.dispute.created` mark the
    payment refunded and archive the combine it bought.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.combine import Combine
from models.payment import Payment
from models.user import User
from services import payments
from services.auth import get_current_user
from services.combine_provision import assert_slot_available, provision_combine
from services.combine_state import record_event
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


class PaymentOut(BaseModel):
    id: int
    combine_id: int | None
    tier: str
    # Simulated dollars. NULL ledger rows (migration grants) read as 0.0 so
    # the shape stays a plain number for the billing tab.
    amount: float
    status: str = Field(
        ...,
        description="paid | activation_paid | reset_paid | reset_credit | "
        "pending | failed | refunded | migration_grant",
    )
    created_at: datetime


class PaymentsHistoryOut(BaseModel):
    payments: list[PaymentOut]


@router.get("/history", response_model=PaymentsHistoryOut)
def payments_history(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> PaymentsHistoryOut:
    """The signed-in user's payment ledger, newest first — purchases,
    monthly renewals, resets (paid or credit-covered), activations.
    Simulated money, real bookkeeping."""
    rows = (
        session.execute(
            select(Payment)
            .where(Payment.user_id == user.id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
        )
        .scalars()
        .all()
    )
    return PaymentsHistoryOut(
        payments=[
            PaymentOut(
                id=p.id,
                combine_id=p.combine_id,
                tier=p.tier,
                amount=float(p.amount or 0.0),
                status=p.status,
                created_at=p.created_at,
            )
            for p in rows
        ]
    )


# Webhook event types we act on; everything else is acked so Stripe stops
# resending (we return 200 either way — "handled" is just telemetry).
_LIFECYCLE_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "checkout.session.expired",
        "charge.refunded",
        "charge.dispute.created",
    }
)


def _locked_payment(session: Session, obj: dict) -> Payment | None:
    """Resolve the Payment an event refers to and take a ROW LOCK on it.

    CONCURRENCY: fulfilment used to be check-then-act — two concurrent
    deliveries of the same event could both read status='pending' and both
    provision (double combine, one payment). The `SELECT … FOR UPDATE`
    serializes deliveries per payment row: the loser blocks until the winner
    commits, then sees the already-flipped status and no-ops. Same pattern
    as the payout double-spend guard in routers/combines.py — and as there,
    FOR UPDATE is a documented no-op on SQLite, whose single-writer
    transaction model already serializes the writers.

    checkout.session.* events carry our metadata directly; charge.* events
    carry it because /checkout copies it onto the PaymentIntent
    (payment_intent_data.metadata), which Stripe propagates to the Charge.
    """
    metadata = obj.get("metadata") or {}
    payment_id = metadata.get("payment_id")
    if not payment_id:
        log.warning("stripe event without payment_id metadata")
        return None
    try:
        pid = int(payment_id)
    except (TypeError, ValueError):
        log.warning("stripe event with malformed payment_id=%r", payment_id)
        return None
    payment = session.execute(
        select(Payment).where(Payment.id == pid).with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        log.warning("webhook references unknown payment_id=%s", payment_id)
    return payment


def _fulfil_checkout(session: Session, payment: Payment, obj: dict) -> bool:
    """checkout.session.completed → mark paid + provision the combine."""
    # Status is (re-)checked UNDER the row lock: a concurrent delivery that
    # won the race has already committed 'paid' by the time we read it.
    if payment.status == "paid":
        return True  # already fulfilled (Stripe retries events)
    if payment.status != "pending":
        # expired/refunded/etc. — don't resurrect a settled payment; leave
        # the anomaly for manual resolution.
        log.error(
            "checkout.session.completed for payment %s in status %r",
            payment.id,
            payment.status,
        )
        return False

    metadata = obj.get("metadata") or {}
    # Amount is read back from Stripe (cents → dollars) — never invented.
    amount_total = obj.get("amount_total")
    if amount_total is not None:
        payment.amount = float(amount_total) / 100.0
    payment.status = "paid"

    user = session.get(User, payment.user_id)
    if user is None:
        session.commit()
        log.error("paid payment %s has no user %s", payment.id, payment.user_id)
        return False

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
        return False

    session.commit()
    return True


def _expire_checkout(session: Session, payment: Payment) -> bool:
    """checkout.session.expired → the shopper abandoned checkout. Flip the
    pending row to failed so it doesn't sit as an eternal 'pending'."""
    if payment.status == "failed":
        return True  # already expired (Stripe retries events)
    if payment.status != "pending":
        # A completed (paid/refunded) payment can't be un-bought by an
        # expiry that raced in late — keep the settled status.
        log.warning(
            "checkout.session.expired for payment %s in status %r",
            payment.id,
            payment.status,
        )
        return False
    payment.status = "failed"
    session.commit()
    return True


def _refund_payment(session: Session, payment: Payment, event_type: str) -> bool:
    """charge.refunded / charge.dispute.created → the money came back (or is
    frozen), so the combine it bought comes out of play: payment 'refunded',
    combine archived, and a combine_events row for the audit trail.

    The archive mirrors POST /combines/{id}/archive (status flip + repoint
    the user's active combine to the newest remaining one) — written
    directly on the models here so the webhook doesn't call into the
    combines router."""
    if payment.status == "refunded":
        return True  # already processed (Stripe retries events)
    payment.status = "refunded"

    combine = (
        session.get(Combine, payment.combine_id)
        if payment.combine_id is not None
        else None
    )
    if combine is not None:
        if combine.status != "archived":
            # Cancel resting orders so a refunded/archived combine leaves no
            # GTC zombie working orders (open positions settle at expiry).
            from services.combine_state import cancel_working_orders
            from services.payout_desk import void_requests

            cancel_working_orders(session, combine.id)
            # Void EVERY live payout request — including approved-unpaid: a
            # refunded/charged-back account gets no re-credit (the account is
            # dead) and must never be mark_paid later. 'cancelled' is
            # terminal and writes no ledger event, so the auto-approve pass
            # and the admin queue both stop seeing these rows.
            void_requests(
                session, combine.id, "chargeback_risk", include_approved=True
            )
            combine.status = "archived"
            user = session.get(User, combine.user_id)
            if user is not None and user.active_combine_id == combine.id:
                replacement = session.execute(
                    select(Combine.id)
                    .where(
                        Combine.user_id == user.id,
                        Combine.status != "archived",
                        Combine.id != combine.id,
                    )
                    .order_by(Combine.created_at.desc(), Combine.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                user.active_combine_id = replacement
                session.add(user)
        reason = (
            "disputed (chargeback)"
            if event_type == "charge.dispute.created"
            else "refunded"
        )
        record_event(
            session,
            combine,
            "refunded",
            f"Payment {reason} — combine archived.",
            amount=payment.amount,
        )
    session.commit()
    return True


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """Stripe → us. Unauthenticated but signature-verified. Idempotent:
    each handler re-checks the payment status under a row lock, so retried
    (or concurrently delivered) events are no-ops."""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = payments.verify_webhook_event(payload, sig)
    except ValueError as exc:
        raise HTTPException(400, "invalid signature") from exc

    event_type = event.get("type")
    if event_type not in _LIFECYCLE_EVENTS:
        return {"received": True, "handled": False}

    obj = (event.get("data") or {}).get("object") or {}
    payment = _locked_payment(session, obj)
    if payment is None:
        return {"received": True, "handled": False}

    if event_type == "checkout.session.completed":
        handled = _fulfil_checkout(session, payment, obj)
    elif event_type == "checkout.session.expired":
        handled = _expire_checkout(session, payment)
    else:  # charge.refunded / charge.dispute.created
        handled = _refund_payment(session, payment, event_type)
    return {"received": True, "handled": handled}
