"""Combine management — purchase, list, rename, archive, activate.

The 5-cap rule lives here: a user holds at most MAX_COMBINES
non-archived combines; archiving frees a slot (history survives —
trades keep their combine_id, the card just leaves the active set).
"Delete" is deliberately archive-only in v1 so no trade history is
ever orphaned.

Purchase uses SIMULATED economics: the product is a paper prop firm, so
no real money moves, but the pricing is real (services/pricing.py). A
purchase records a paid payments row at the matrix monthly price; once an
account funds it is activated via /activate-account ($149 on the activation
path, $0 on no-activation). When Stripe lands, /api/payments/checkout takes
over the charge and this endpoint becomes a fallback.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from services import pricing
from services.account_tiers import TIERS
from services.auth import get_current_user
from services.combine_provision import MAX_COMBINES, provision_combine
from services.combine_state import combine_snapshot, record_event

router = APIRouter(prefix="/api/combines", tags=["combines"])

# Idempotency window for payout requests: a second payout on the same combine
# within this many seconds is rejected as a likely duplicate (double-click, a
# retried request, or two racing tabs). The FOR UPDATE lock below already makes
# double-booking impossible; this is the belt to that suspenders, turning a
# duplicate into a clear 409 instead of two legitimate-looking events.
PAYOUT_IDEMPOTENCY_WINDOW_S = 10

# Idempotency window for payout requests: a second payout on the same combine
# within this many seconds is rejected as a likely duplicate (double-click, a
# retried request, or two racing tabs). The FOR UPDATE lock below already makes
# double-booking impossible; this is the belt to that suspenders, turning a
# duplicate into a clear 409 instead of two legitimate-looking events.
PAYOUT_IDEMPOTENCY_WINDOW_S = 10


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
    max_contracts: int = Field(
        ..., description="Scaling-plan cap: max contracts per position at the current built equity."
    )
    # --- funded-account lifecycle ---
    funded: bool = Field(..., description="True once the eval passed (auto-funded).")
    funded_at: datetime | None = None
    payout_eligible: float = Field(
        ..., description="Available payout: trader's split of profit, net of prior requests."
    )
    payout_requested: float = Field(
        ..., description="Lifetime payout already requested on this account."
    )
    # --- pricing + activation ---
    pricing_path: str = Field(..., description="activation | no_activation.")
    profit_split: float = Field(..., description="Trader's profit share (0.80 or 0.50).")
    monthly_price: float = Field(..., description="Monthly subscription for this combine.")
    activation_required: bool = Field(
        ..., description="Funded but not yet activated — payouts locked until the fee is paid."
    )
    activation_fee: float = Field(
        ..., description="Activation fee owed to unlock payouts ($149 on the activation path, else 0)."
    )
    funded_activated: bool = Field(
        ..., description="True once the funded account is activated (payouts unlocked)."
    )
    # --- copy trading ---
    copy_follow: bool = Field(
        ..., description="True if this combine mirrors the lead combine's trades."
    )
    copy_multiplier: float = Field(
        ..., description="Size multiplier applied to the lead's contracts before clamping."
    )
    copy_stop_loss: float | None = Field(
        None, description="Per-follower stop-loss override (underlying price); null = inherit lead's."
    )
    copy_take_profit: float | None = Field(
        None, description="Per-follower take-profit override (underlying price); null = inherit lead's."
    )
    created_at: datetime


class CombinesOut(BaseModel):
    combines: list[CombineOut]
    active_combine_id: int | None
    slots_used: int = Field(..., description="Non-archived combines (counts against the cap).")
    slots_total: int
    copy_lead_combine_id: int | None = Field(
        None, description="The combine whose trades mirror to followers (None = off)."
    )


class FollowerConfig(BaseModel):
    combine_id: int
    multiplier: float = Field(1.0, ge=0.1, le=10.0)
    # Per-follower bracket overrides (underlying price levels). null = inherit
    # the lead trade's stop_loss / take_profit on each mirrored open.
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)


class CopyConfigIn(BaseModel):
    lead_combine_id: int | None = None
    followers: list[FollowerConfig] = Field(default_factory=list)


class PurchaseIn(BaseModel):
    tier: Literal["50K", "100K", "150K"]
    name: str | None = Field(default=None, min_length=1, max_length=64)
    # Pricing path + profit split, chosen on the buy screen. Defaults match
    # the headline plan (standard 80/20 split on the activation path).
    pricing_path: Literal["activation", "no_activation"] = "activation"
    split: Literal["80_20", "50_50"] = "80_20"


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
    type: str = Field(
        ..., description="funded | failed | settled | reset | payout | activation"
    )
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
        max_contracts=snap.max_contracts,
        funded=snap.funded,
        funded_at=snap.funded_at,
        payout_eligible=available,
        payout_requested=requested,
        pricing_path=snap.pricing_path,
        profit_split=snap.profit_split,
        monthly_price=pricing.monthly_price(
            combine.tier, snap.pricing_path, snap.profit_split
        ),
        activation_required=snap.activation_required,
        activation_fee=snap.activation_fee,
        funded_activated=snap.funded_activated,
        copy_follow=combine.copy_follow,
        copy_multiplier=combine.copy_multiplier,
        copy_stop_loss=combine.copy_stop_loss,
        copy_take_profit=combine.copy_take_profit,
        created_at=combine.created_at,
    )


def _owned_combine(session: Session, user: User, combine_id: int) -> Combine:
    combine = session.execute(
        select(Combine).where(Combine.id == combine_id, Combine.user_id == user.id)
    ).scalar_one_or_none()
    if combine is None:
        raise HTTPException(404, f"combine {combine_id} not found")
    return combine


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
        copy_lead_combine_id=user.copy_lead_combine_id,
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


@router.put("/copy-config", response_model=CombinesOut)
def set_copy_config(
    payload: CopyConfigIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombinesOut:
    """Set copy trading: which combine is the lead and which follow it.

    The lead's trades mirror to every follower (services/copy_trade). The lead
    can't also be a follower (it's removed from the set). All ids must be the
    user's own combines. Passing lead_combine_id=null turns copy trading off."""
    owned = {
        c.id: c
        for c in session.execute(
            select(Combine).where(Combine.user_id == user.id)
        ).scalars().all()
    }
    lead = payload.lead_combine_id
    if lead is not None and lead not in owned:
        raise HTTPException(404, f"combine {lead} not found")
    # combine_id → follower config, excluding the lead (it can't follow itself).
    fmap = {f.combine_id: f for f in payload.followers if f.combine_id != lead}
    for fid in fmap:
        if fid not in owned:
            raise HTTPException(404, f"combine {fid} not found")

    user.copy_lead_combine_id = lead
    for cid, combine in owned.items():
        cfg = fmap.get(cid)
        if cfg is not None:
            combine.copy_follow = True
            combine.copy_multiplier = cfg.multiplier
            combine.copy_stop_loss = cfg.stop_loss
            combine.copy_take_profit = cfg.take_profit
        else:
            combine.copy_follow = False
            # Clear stale overrides when a combine stops following so they
            # don't silently reapply if it follows again later.
            combine.copy_stop_loss = None
            combine.copy_take_profit = None
        session.add(combine)
    session.add(user)
    session.commit()
    return list_combines(user=user, session=session)


@router.post("/purchase", response_model=CombineOut, status_code=201)
def purchase_combine(
    payload: PurchaseIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    # Simulated paid purchase: no real money moves, but the recorded amount
    # is the real matrix monthly price (provision_combine fills it from the
    # chosen path + split). When Stripe is on the frontend routes through
    # /api/payments/checkout instead and the webhook provisions with the
    # Stripe-read amount.
    split = pricing.split_value(payload.split)
    payment = Payment(
        user_id=user.id,
        tier=payload.tier,
        amount=None,  # set to the matrix monthly price in provision_combine
        status="paid",
    )
    session.add(payment)
    combine = provision_combine(
        session,
        user,
        tier_key=payload.tier,
        name=payload.name,
        payment=payment,
        pricing_path=payload.pricing_path,
        profit_split=split,
    )
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
    """Request a payout on a FUNDED, ACTIVATED account: the trader's split
    (80/20 or 50/50) of realized profit, net of prior requests. Simulated —
    records a payout event but moves no money.

    CONCURRENCY (P0): two payout requests racing on the same combine used to
    each read `available` before either booked an event, so both could book the
    full balance — a double-spend. Fixed two ways here:

      1. We take a ROW LOCK on the combine (`SELECT … FOR UPDATE`) and read
         `available` (eligible − prior requests) UNDER that lock, in the SAME
         transaction that books the payout event. A concurrent request blocks on
         the lock until the first commits, then sees the just-booked event in its
         own `_payouts_requested` sum — so the second can never re-book the same
         balance. (On SQLite FOR UPDATE is a documented no-op, but SQLite's
         single-writer transaction model already serializes writers, so the
         invariant holds on both backends.)

      2. An idempotency guard rejects a duplicate payout on the same combine
         within PAYOUT_IDEMPOTENCY_WINDOW_S seconds (double-click / retry / two
         tabs), turning it into a clean 409 rather than a second event.
    """
    # Snapshot first (outside the lock) — this may COMMIT a pending settlement,
    # which would release any lock we held, so we compute the gating booleans +
    # the gross eligible amount here, then re-lock for the booking below.
    combine = _owned_combine(session, user, combine_id)
    snap = combine_snapshot(session, combine)
    if not snap.funded:
        raise HTTPException(409, "account is not funded")
    if snap.activation_required:
        raise HTTPException(
            409,
            f"funded account not activated — pay the ${snap.activation_fee:,.0f} "
            "activation fee to unlock payouts",
        )

    # Re-acquire the combine row WITH a write lock, opening the booking
    # transaction. Everything from here to the commit is serialized per combine.
    locked = session.execute(
        select(Combine)
        .where(Combine.id == combine.id, Combine.user_id == user.id)
        .with_for_update()
    ).scalar_one_or_none()
    if locked is None:
        raise HTTPException(404, f"combine {combine_id} not found")

    now = datetime.now(timezone.utc)

    # Idempotency: a recent payout on this combine is treated as a duplicate.
    cutoff = now - timedelta(seconds=PAYOUT_IDEMPOTENCY_WINDOW_S)
    recent = session.execute(
        select(CombineEvent.id)
        .where(
            CombineEvent.combine_id == combine.id,
            CombineEvent.type == "payout",
            CombineEvent.created_at >= cutoff,
        )
        .limit(1)
    ).scalar_one_or_none()
    if recent is not None:
        raise HTTPException(
            409,
            "a payout was just requested on this account — please wait a moment "
            "before requesting another",
        )

    # `available` is read UNDER the lock so a racing request can't have booked
    # against the same balance without us seeing it.
    available = max(0.0, snap.payout_eligible - _payouts_requested(session, combine.id))
    if available <= 0:
        raise HTTPException(409, "no payout currently available")
    record_event(
        session,
        locked,
        "payout",
        f"Payout requested — ${available:,.2f}.",
        amount=available,
    )
    session.commit()
    return PayoutOut(combine_id=combine.id, amount=available, requested_at=now)


@router.post("/{combine_id}/activate-account", response_model=CombineOut)
def activate_account(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    """Activate a funded account — one unified flow for both paths. Charges
    the $149 fee on the activation path and $0 on the no-activation path
    (simulated), records the activation event, and unlocks payouts. 409 if
    the account isn't funded or is already activated."""
    combine = _owned_combine(session, user, combine_id)
    snap = combine_snapshot(session, combine)
    if not snap.funded:
        raise HTTPException(409, "account is not funded")
    if not snap.activation_required:
        raise HTTPException(409, "funded account is already activated")
    fee = pricing.activation_fee(combine.pricing_path)
    now = datetime.now(timezone.utc)
    combine.funded_activated_at = now
    # Only the activation path charges; no $0 payment rows for no-activation.
    if fee > 0:
        session.add(
            Payment(
                user_id=user.id,
                combine_id=combine.id,
                tier=combine.tier,
                amount=fee,
                status="activation_paid",
            )
        )
    record_event(
        session,
        combine,
        "activation",
        f"Funded account activated — ${fee:,.0f} activation fee paid."
        if fee > 0
        else "Funded account activated (no activation fee).",
        amount=fee,
    )
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
