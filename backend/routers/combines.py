"""Combine management — purchase, list, rename, archive, activate.

The 5-cap rule lives here: a user holds at most MAX_COMBINES
non-archived combines; archiving frees a slot (history survives —
trades keep their combine_id, the card just leaves the active set).
"Delete" is deliberately archive-only in v1 so no trade history is
ever orphaned.

Purchase is PLACEHOLDER ECONOMICS: a payments row with amount=NULL and
status='placeholder_paid' is written in the same transaction as the
combine. When Stripe lands, this endpoint becomes the post-checkout
fulfillment hook and the row gains a real amount/status.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.combine import Combine
from models.payment import Payment
from models.user import User
from services.account_tiers import TIERS
from services.auth import get_current_user
from services.combine_objectives import generate_account_code
from services.combine_state import combine_snapshot

router = APIRouter(prefix="/api/combines", tags=["combines"])

MAX_COMBINES = 5


class CombineOut(BaseModel):
    id: int
    name: str
    tier: str
    account_code: str
    status: str = Field(..., description="Lifecycle: active | archived.")
    outcome: str = Field(
        ..., description="Settlement outcome: active | passed | failed (permanent)."
    )
    starting_balance: float
    realized_pnl: float
    balance: float
    hwm: float
    settled_hwm: float
    mll: float
    dll_used: float
    dll_budget: float
    day_locked: bool
    profit_target: float
    objective_progress: float
    created_at: datetime


class CombinesOut(BaseModel):
    combines: list[CombineOut]
    active_combine_id: int | None
    slots_used: int = Field(..., description="Non-archived combines (counts against the cap).")
    slots_total: int


class PurchaseIn(BaseModel):
    tier: Literal["50K", "100K", "150K"]
    name: str | None = Field(default=None, min_length=1, max_length=64)


class RenameIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


def _to_out(session: Session, combine: Combine) -> CombineOut:
    snap = combine_snapshot(session, combine)
    return CombineOut(
        id=combine.id,
        name=combine.name,
        tier=combine.tier,
        account_code=combine.account_code,
        status=combine.status,
        outcome=snap.outcome,
        starting_balance=snap.starting_balance,
        realized_pnl=snap.realized_pnl,
        balance=snap.balance,
        hwm=snap.hwm,
        settled_hwm=snap.settled_hwm,
        mll=snap.mll,
        dll_used=snap.dll_used,
        dll_budget=snap.dll_budget,
        day_locked=snap.day_locked,
        profit_target=snap.profit_target,
        objective_progress=snap.objective_progress,
        created_at=combine.created_at,
    )


def _owned_combine(session: Session, user: User, combine_id: int) -> Combine:
    combine = session.execute(
        select(Combine).where(Combine.id == combine_id, Combine.user_id == user.id)
    ).scalar_one_or_none()
    if combine is None:
        raise HTTPException(404, f"combine {combine_id} not found")
    return combine


def _slots_used(session: Session, user: User) -> int:
    return len(
        session.execute(
            select(Combine.id).where(
                Combine.user_id == user.id, Combine.status != "archived"
            )
        ).all()
    )


@router.get("", response_model=CombinesOut)
def list_combines(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombinesOut:
    combines = session.execute(
        select(Combine)
        .where(Combine.user_id == user.id)
        .order_by(Combine.created_at.desc(), Combine.id.desc())
    ).scalars().all()
    return CombinesOut(
        combines=[_to_out(session, c) for c in combines],
        active_combine_id=user.active_combine_id,
        slots_used=sum(1 for c in combines if c.status != "archived"),
        slots_total=MAX_COMBINES,
    )


@router.post("/purchase", response_model=CombineOut, status_code=201)
def purchase_combine(
    payload: PurchaseIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    if _slots_used(session, user) >= MAX_COMBINES:
        raise HTTPException(
            409,
            f"combine limit reached — you can hold at most {MAX_COMBINES} "
            "combines; archive one to free a slot",
        )
    tier = TIERS[payload.tier]

    # PLACEHOLDER — Stripe integration pending. Records the purchase
    # event with no amount; the UI shows $XX until pricing is decided.
    payment = Payment(
        user_id=user.id,
        tier=payload.tier,
        amount=None,
        status="placeholder_paid",
    )
    session.add(payment)

    combine = Combine(
        user_id=user.id,
        tier=payload.tier,
        name=(payload.name or "").strip() or f"{payload.tier} Combine",
        account_code=generate_account_code(session, payload.tier, user.id),
        hwm=tier.starting_balance,
        settled_hwm=tier.starting_balance,
        status="active",
        outcome="active",
    )
    session.add(combine)
    session.flush()
    payment.combine_id = combine.id

    # First combine auto-activates so the terminal works immediately.
    if user.active_combine_id is None:
        user.active_combine_id = combine.id
        session.add(user)

    session.commit()
    session.refresh(combine)
    return _to_out(session, combine)


@router.patch("/{combine_id}", response_model=CombineOut)
def rename_combine(
    combine_id: int,
    payload: RenameIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    combine = _owned_combine(session, user, combine_id)
    combine.name = payload.name.strip()
    session.commit()
    session.refresh(combine)
    return _to_out(session, combine)


@router.post("/{combine_id}/archive", response_model=CombineOut)
def archive_combine(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    combine = _owned_combine(session, user, combine_id)
    if combine.status != "archived":
        combine.status = "archived"
        # Archiving the active combine repoints to the newest remaining
        # active one (or clears the selection).
        if user.active_combine_id == combine.id:
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
        session.commit()
        session.refresh(combine)
    return _to_out(session, combine)


@router.post("/{combine_id}/activate")
def activate_combine(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    combine = _owned_combine(session, user, combine_id)
    if combine.status == "archived":
        raise HTTPException(409, "cannot activate an archived combine")
    user.active_combine_id = combine.id
    session.add(user)
    session.commit()
    # Return the full header payload so the frontend can cache-swap it,
    # mirroring the legacy switch-tier flow.
    from routers.account import get_account_state

    return get_account_state(user=user, session=session)
