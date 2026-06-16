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

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from models.combine import Combine
from models.combine_event import CombineEvent
from models.payment import Payment
from models.user import User
from services.account_tiers import TIERS
from services.auth import get_current_user
from services.combine_objectives import generate_account_code
from services.combine_state import combine_snapshot, record_event

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
    # --- funded-account lifecycle ---
    funded: bool = Field(..., description="True once the eval passed (auto-funded).")
    funded_at: datetime | None = None
    payout_eligible: float = Field(
        ..., description="Available payout: trader's split of profit, net of prior requests."
    )
    payout_requested: float = Field(
        ..., description="Lifetime payout already requested on this account."
    )
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


class PayoutOut(BaseModel):
    combine_id: int
    amount: float = Field(..., description="Amount requested in this payout.")
    requested_at: datetime


class CombineEventOut(BaseModel):
    id: int
    combine_id: int
    combine_name: str | None
    type: str = Field(..., description="funded | failed | settled | reset | payout")
    message: str
    amount: float | None
    created_at: datetime


def _payouts_requested(session: Session, combine_id: int) -> float:
    """Sum of payout amounts already requested on this combine."""
    rows = session.execute(
        select(CombineEvent.amount).where(
            CombineEvent.combine_id == combine_id, CombineEvent.type == "payout"
        )
    ).all()
    return float(sum((r[0] or 0.0) for r in rows))


def _to_out(session: Session, combine: Combine) -> CombineOut:
    snap = combine_snapshot(session, combine)
    requested = _payouts_requested(session, combine.id)
    available = max(0.0, snap.payout_eligible - requested)
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
        funded=snap.funded,
        funded_at=snap.funded_at,
        payout_eligible=available,
        payout_requested=requested,
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


@router.get("/events", response_model=list[CombineEventOut])
def list_events(
    limit: int = 50,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[CombineEventOut]:
    """The user's recent lifecycle events across all combines, newest
    first — funded / failed / settled / reset / payout. Drives the
    dashboard live-feed. Note: most transitions are written lazily by
    combine_snapshot on read, so polling account/state keeps this fresh."""
    names = dict(
        session.execute(
            select(Combine.id, Combine.name).where(Combine.user_id == user.id)
        ).all()
    )
    rows = session.execute(
        select(CombineEvent)
        .where(CombineEvent.user_id == user.id)
        .order_by(CombineEvent.created_at.desc(), CombineEvent.id.desc())
        .limit(max(1, min(limit, 200)))
    ).scalars().all()
    return [
        CombineEventOut(
            id=e.id,
            combine_id=e.combine_id,
            combine_name=names.get(e.combine_id),
            type=e.type,
            message=e.message,
            amount=e.amount,
            created_at=e.created_at,
        )
        for e in rows
    ]


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


@router.post("/{combine_id}/reset", response_model=CombineOut)
def reset_combine(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    """Restart a FAILED evaluation. Stamps eval_reset_at (the engine then
    counts only trades opened after it), re-baselines the HWM/MLL to the
    tier start, and clears the outcome — the trade history is preserved."""
    combine = _owned_combine(session, user, combine_id)
    if combine.outcome != "failed":
        raise HTTPException(409, "only a failed combine can be reset")
    now = datetime.now(timezone.utc)
    tier = TIERS[combine.tier]
    combine.outcome = "active"
    combine.funded_at = None
    combine.eval_reset_at = now
    combine.hwm = tier.starting_balance
    combine.settled_hwm = tier.starting_balance
    # Treat the reset instant as the day's settlement so the next read
    # doesn't immediately log a spurious "settled" event.
    combine.last_settled_at = now
    record_event(session, combine, "reset", "Evaluation reset — fresh start.")
    session.add(combine)
    session.commit()
    session.refresh(combine)
    return _to_out(session, combine)


@router.post("/{combine_id}/payout", response_model=PayoutOut)
def request_payout(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> PayoutOut:
    """Request a payout on a FUNDED account: the trader's 50% split of
    realized profit, net of prior requests. Simulated — records a payout
    event but moves no money (Stripe/banking lands with real pricing)."""
    combine = _owned_combine(session, user, combine_id)
    snap = combine_snapshot(session, combine)
    if not snap.funded:
        raise HTTPException(409, "account is not funded")
    available = max(0.0, snap.payout_eligible - _payouts_requested(session, combine.id))
    if available <= 0:
        raise HTTPException(409, "no payout currently available")
    now = datetime.now(timezone.utc)
    record_event(
        session,
        combine,
        "payout",
        f"Payout requested — ${available:,.2f}.",
        amount=available,
    )
    session.commit()
    return PayoutOut(combine_id=combine.id, amount=available, requested_at=now)


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
