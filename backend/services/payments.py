"""Stripe payment gateway — OPT-IN.

The whole module is dormant unless `settings.stripe_secret_key` is set: the
router checks `stripe_enabled()` and falls back to the free placeholder
flow when it's False, so a fresh install behaves exactly as before.

Design notes:
  - NO dollar amounts live here. Each tier maps to a Stripe **Price ID**
    (configured in .env / the Stripe dashboard). The amount actually
    charged is read back from the completed Checkout Session, never
    invented in code.
  - The `stripe` SDK is imported LAZILY inside the two boundary functions
    (`_create_checkout_session`, `_construct_event`) so the app boots — and
    the rest of the test suite runs — even if the package isn't installed.
  - Tests monkeypatch those two boundary functions, so no test ever touches
    the network or needs real Stripe credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import settings

log = logging.getLogger(__name__)


def stripe_enabled() -> bool:
    """True when Stripe is configured. Gate every payment path on this."""
    return bool(settings.stripe_secret_key)


def webhook_configured() -> bool:
    return bool(settings.stripe_webhook_secret)


# Tier → Stripe Price ID. Blank means that tier isn't purchasable yet.
def _price_map() -> dict[str, str]:
    return {
        "50K": settings.stripe_price_50k,
        "100K": settings.stripe_price_100k,
        "150K": settings.stripe_price_150k,
    }


def price_id_for(tier: str) -> str | None:
    """The configured Stripe Price ID for a tier, or None if unset."""
    return _price_map().get(tier) or None


def purchasable_tiers() -> dict[str, bool]:
    """Per-tier flag: True when a Price ID is configured for it."""
    return {tier: bool(pid) for tier, pid in _price_map().items()}


@dataclass(frozen=True)
class CheckoutSession:
    url: str
    session_id: str


# ---------------------------------------------------------------------------
# Public API used by the router
# ---------------------------------------------------------------------------


def create_checkout_session(
    *,
    user_id: int,
    tier: str,
    price_id: str,
    payment_id: int,
    combine_name: str | None,
) -> CheckoutSession:
    """Create a Stripe Checkout Session for one combine purchase.

    Metadata carries everything the webhook needs to provision the combine
    (payment_id, user_id, tier, combine_name) so fulfilment is decoupled
    from this request.
    """
    metadata = {
        "payment_id": str(payment_id),
        "user_id": str(user_id),
        "tier": tier,
        "combine_name": combine_name or "",
    }
    return _create_checkout_session(
        price_id=price_id,
        metadata=metadata,
        success_url=settings.stripe_success_url,
        cancel_url=settings.stripe_cancel_url,
        client_reference_id=str(user_id),
    )


def verify_webhook_event(payload: bytes, sig_header: str) -> dict:
    """Verify a webhook payload's signature and return the parsed event.

    Raises ValueError on a bad/missing signature (the router turns that into
    a 400). Never trust an unverified webhook — anyone can POST to it.
    """
    if not settings.stripe_webhook_secret:
        raise ValueError("stripe webhook secret not configured")
    return _construct_event(payload, sig_header, settings.stripe_webhook_secret)


# ---------------------------------------------------------------------------
# Boundary functions — the ONLY places that touch the stripe SDK. Lazy import
# keeps the package optional; tests monkeypatch these two.
# ---------------------------------------------------------------------------


def _stripe():
    """Import + configure the stripe SDK lazily. Raises if not installed."""
    try:
        import stripe  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise RuntimeError(
            "stripe is enabled but the 'stripe' package is not installed "
            "(add it to dependencies)"
        ) from exc
    stripe.api_key = settings.stripe_secret_key
    return stripe


def _create_checkout_session(
    *,
    price_id: str,
    metadata: dict,
    success_url: str,
    cancel_url: str,
    client_reference_id: str,
) -> CheckoutSession:  # pragma: no cover - network boundary, mocked in tests
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        client_reference_id=client_reference_id,
        metadata=metadata,
        payment_intent_data={"metadata": metadata},
    )
    return CheckoutSession(url=session.url, session_id=session.id)


def _construct_event(
    payload: bytes, sig_header: str, secret: str
) -> dict:  # pragma: no cover - network boundary, mocked in tests
    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except Exception as exc:  # noqa: BLE001 - SDK raises several types
        raise ValueError(f"invalid stripe signature: {exc}") from exc
    # construct_event returns a stripe object; normalise to a plain dict.
    return dict(event)
