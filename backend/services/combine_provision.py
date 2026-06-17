"""Combine provisioning — the single place a combine is created.

Both purchase paths converge here:
  - the free PLACEHOLDER flow (`POST /api/combines/purchase`), and
  - the Stripe fulfilment hook (`checkout.session.completed` webhook),

so a paid combine is provisioned byte-for-byte the same as a placeholder
one — account code, HWM seeding, payment linkage, and first-combine
auto-activation all live in one function instead of being duplicated.

The caller owns the transaction (this only `flush`es to obtain the combine
id for the payment link); commit/rollback stays with the request handler so
the whole purchase is atomic.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.combine import Combine
from models.payment import Payment
from models.user import User
from services.account_tiers import TIERS
from services.combine_objectives import generate_account_code

# Max non-archived combines a user may hold at once; archiving frees a slot.
MAX_COMBINES = 5


def slots_used(session: Session, user: User) -> int:
    """Count the user's non-archived combines (what the cap measures)."""
    return len(
        session.execute(
            select(Combine.id).where(
                Combine.user_id == user.id, Combine.status != "archived"
            )
        ).all()
    )


def assert_slot_available(session: Session, user: User) -> None:
    """Raise 409 if the user is already at the combine cap."""
    if slots_used(session, user) >= MAX_COMBINES:
        raise HTTPException(
            409,
            f"combine limit reached — you can hold at most {MAX_COMBINES} "
            "combines; archive one to free a slot",
        )


def provision_combine(
    session: Session,
    user: User,
    *,
    tier_key: str,
    name: str | None,
    payment: Payment,
) -> Combine:
    """Create a combine for `user` on `tier_key`, linking `payment` to it.

    Enforces the slot cap (raises 409). Seeds the running + settled HWM to
    the tier's starting balance and auto-activates the user's first combine
    so the terminal works immediately. Flushes (not commits) — the caller
    commits as part of its own transaction.
    """
    assert_slot_available(session, user)
    tier = TIERS[tier_key]

    combine = Combine(
        user_id=user.id,
        tier=tier_key,
        name=(name or "").strip() or f"{tier_key} Combine",
        account_code=generate_account_code(session, tier_key, user.id),
        hwm=tier.starting_balance,
        settled_hwm=tier.starting_balance,
        status="active",
        outcome="active",
    )
    session.add(combine)
    session.flush()  # assign combine.id for the payment link
    payment.combine_id = combine.id

    # First combine auto-activates so the terminal works immediately.
    if user.active_combine_id is None:
        user.active_combine_id = combine.id
        session.add(user)

    return combine
