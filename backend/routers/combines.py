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
path, $0 on no-activation). With Stripe configured the free purchase path
is CLOSED — /api/payments/checkout owns the charge and this endpoint 409s.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database import get_session
from models.combine import Combine
from models.combine_event import CombineEvent
from models.payment import Payment
from models.user import User
from services import payments, pricing
from services.account_tiers import TIERS
from services.auth import get_current_user
from services.combine_provision import MAX_COMBINES, provision_combine
from services.combine_state import (
    PAYOUT_DEBIT_TYPES,
    combine_snapshot,
    has_open_book,
    realized_by_trading_day,
    record_event,
)
from services.rate_limit import enforce_user, financial_limiter

router = APIRouter(prefix="/api/combines", tags=["combines"])

# Idempotency window for payout requests: a second payout on the same combine
# within this many seconds is rejected as a likely duplicate (double-click, a
# retried request, or two racing tabs). The FOR UPDATE lock below already makes
# double-booking impossible; this is the belt to that suspenders, turning a
# duplicate into a clear 409 instead of two legitimate-looking events.
PAYOUT_IDEMPOTENCY_WINDOW_S = 10

# Payout policy (Topstep-aligned): a request must be at least the minimum,
# the account needs a track record of winning days in the FUNDED stage (a
# day whose realized P&L meets the winning-day bar), and requests are paced
# to one per interval. All are 409s with distinct human-readable details.
PAYOUT_MIN_AMOUNT = 125.0
PAYOUT_MIN_WINNING_DAYS = 5
PAYOUT_WINNING_DAY_PROFIT = 150.0
PAYOUT_MIN_INTERVAL_H = 24.0


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
    # --- billing ("Billed monthly, cancel anytime") ---
    paid_through: datetime | None = Field(
        None,
        description="End of the current paid 30-day period (auto-renews unless canceled).",
    )
    cancel_at_period_end: bool = Field(
        ...,
        description="True when the subscription ends (combine archives) at paid_through.",
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
    reset_credits: int = Field(
        0,
        description="Banked free reset credits — one per monthly renewal, "
        "spent automatically on the next reset.",
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


class PayoutIn(BaseModel):
    # Absent (or null) → request the full available payout.
    amount: float | None = Field(default=None, gt=0)


class PayoutOut(BaseModel):
    combine_id: int
    amount: float = Field(..., description="Amount requested in this payout.")
    requested_at: datetime


class CombineEventOut(BaseModel):
    id: int
    combine_id: int
    combine_name: str | None
    type: str = Field(
        ...,
        description="funded | failed | settled | reset | payout_requested | "
        "payout_approved | activation | renewal | sub_cancel | sub_resume | "
        "sub_ended (legacy data may carry plain 'payout')",
    )
    message: str
    amount: float | None
    created_at: datetime


def _payouts_requested(session: Session, combine_id: int) -> float:
    """Sum of payout amounts already requested on this combine — the debit
    events only (PAYOUT_DEBIT_TYPES), never the approvals that echo them."""
    rows = session.execute(
        select(CombineEvent.amount).where(
            CombineEvent.combine_id == combine_id,
            CombineEvent.type.in_(PAYOUT_DEBIT_TYPES),
        )
    ).all()
    return float(sum((r[0] or 0.0) for r in rows))


def _payouts_requested_by_combine(
    session: Session, combine_ids: list[int]
) -> dict[int, float]:
    """Per-combine sum of requested payouts for MANY combines in ONE grouped
    query — the batched form of `_payouts_requested`, used by list_combines to
    kill its N+1 (was one sum query per card). Combines with no payout events
    are simply absent from the map; callers default them to 0.0."""
    if not combine_ids:
        return {}
    rows = session.execute(
        select(
            CombineEvent.combine_id,
            func.coalesce(func.sum(CombineEvent.amount), 0),
        )
        .where(
            CombineEvent.combine_id.in_(combine_ids),
            CombineEvent.type.in_(PAYOUT_DEBIT_TYPES),
        )
        .group_by(CombineEvent.combine_id)
    ).all()
    return {cid: float(total or 0.0) for cid, total in rows}


def _to_out(
    session: Session, combine: Combine, *, requested: float | None = None
) -> CombineOut:
    snap = combine_snapshot(session, combine)
    # `requested` may be precomputed by a batched grouped query (list_combines)
    # to avoid a per-combine round-trip; fall back to the single-combine sum
    # when called in isolation (purchase/rename/archive/etc.).
    if requested is None:
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
        paid_through=combine.paid_through,
        cancel_at_period_end=combine.cancel_at_period_end,
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
    # N+1 fix: one grouped query for every combine's requested-payout sum,
    # instead of `_payouts_requested` firing once per card inside `_to_out`.
    requested_by_id = _payouts_requested_by_combine(session, [c.id for c in combines])
    return CombinesOut(
        combines=[
            _to_out(session, c, requested=requested_by_id.get(c.id, 0.0))
            for c in combines
        ],
        active_combine_id=user.active_combine_id,
        slots_used=sum(1 for c in combines if c.status != "archived"),
        slots_total=MAX_COMBINES,
        copy_lead_combine_id=user.copy_lead_combine_id,
        reset_credits=int(user.reset_credits or 0),
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
    # Paywall: with Stripe configured, checkout is the ONLY purchase path —
    # this endpoint would otherwise provision a combine for free. Checked
    # before the throttle (like checkout's Stripe-off short-circuit) so a
    # misrouted call doesn't consume the purchase budget.
    if payments.stripe_enabled():
        raise HTTPException(
            409,
            "purchases go through Stripe checkout — POST /api/payments/checkout",
        )
    # Per-user throttle: provisioning a combine writes a payment + a combine row;
    # a double-click or scripted loop shouldn't be able to spin up many at once.
    enforce_user(financial_limiter, user.id, "purchase")
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
    """Restart a FAILED evaluation. A banked free reset credit (one per
    monthly rebill, jobs/renew_combines) covers the reset first; otherwise
    books a reset fee at the combine's monthly rate (Topstep model). Either
    way it stamps eval_reset_at (the engine then counts only trades opened
    after it), re-baselines the HWM/MLL to the tier start, and clears the
    outcome — the trade history is preserved. Requires a FLAT book: an open
    position's eventual P&L would escape eval accounting entirely (only
    entry_date >= eval_reset_at counts)."""
    # Per-user throttle: a reset books a fee payment — same budget as the
    # other financial endpoints (purchase / payout / activation).
    enforce_user(financial_limiter, user.id, "reset")
    combine = _owned_combine(session, user, combine_id)
    if combine.outcome != "failed":
        raise HTTPException(409, "only a failed combine can be reset")
    if has_open_book(session, combine.id):
        raise HTTPException(
            409,
            "close all open positions and cancel working orders before resetting",
        )
    now = datetime.now(timezone.utc)
    tier = TIERS[combine.tier]
    # Banked credits are spent before any money: the $0 ledger row keeps the
    # payment history complete (status 'reset_credit' vs 'reset_paid').
    credits = int(user.reset_credits or 0)
    if credits > 0:
        user.reset_credits = credits - 1
        session.add(user)
        fee = 0.0
        status = "reset_credit"
        message = (
            "Evaluation reset — free reset credit used "
            f"({user.reset_credits} remaining)."
        )
    else:
        fee = pricing.reset_fee(combine.tier, combine.pricing_path, combine.profit_split)
        status = "reset_paid"
        message = f"Evaluation reset — ${fee:,.0f} reset fee paid."
    session.add(
        Payment(
            user_id=user.id,
            combine_id=combine.id,
            tier=combine.tier,
            amount=fee,
            status=status,
        )
    )
    combine.outcome = "active"
    combine.funded_at = None
    # A terminated funded account resets back to the EVAL stage: clear the
    # activation stamp + accounting epoch along with the funding itself.
    combine.funded_activated_at = None
    combine.funded_epoch_at = None
    combine.eval_reset_at = now
    combine.hwm = tier.starting_balance
    combine.settled_hwm = tier.starting_balance
    # Treat the reset instant as the day's settlement so the next read
    # doesn't immediately log a spurious "settled" event.
    combine.last_settled_at = now
    record_event(
        session,
        combine,
        "reset",
        message,
        amount=fee,
    )
    session.add(combine)
    session.commit()
    session.refresh(combine)
    return _to_out(session, combine)


@router.post("/{combine_id}/cancel", response_model=CombineOut)
def cancel_subscription(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    """'Cancel anytime': flag the combine to archive at the end of the paid
    period instead of auto-renewing. It stays fully tradable (whatever its
    outcome) until paid_through; the renewal job then archives it. Idempotent
    — re-canceling records nothing new."""
    combine = _owned_combine(session, user, combine_id)
    if combine.status == "archived":
        raise HTTPException(409, "combine is already archived")
    if not combine.cancel_at_period_end:
        combine.cancel_at_period_end = True
        record_event(
            session,
            combine,
            "sub_cancel",
            "Subscription canceled — active until the end of the paid period.",
        )
        session.add(combine)
        session.commit()
        session.refresh(combine)
    return _to_out(session, combine)


@router.post("/{combine_id}/resume", response_model=CombineOut)
def resume_subscription(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    """Undo a pending cancel before the period ends — auto-renew re-enables.
    409 once the combine is archived (the boundary already passed and the
    subscription ended). Idempotent — resuming an un-canceled combine is a
    no-op."""
    combine = _owned_combine(session, user, combine_id)
    if combine.status == "archived":
        raise HTTPException(
            409, "subscription already ended — the combine is archived"
        )
    if combine.cancel_at_period_end:
        combine.cancel_at_period_end = False
        record_event(
            session,
            combine,
            "sub_resume",
            "Subscription resumed — auto-renew re-enabled.",
        )
        session.add(combine)
        session.commit()
        session.refresh(combine)
    return _to_out(session, combine)


@router.post("/{combine_id}/payout", response_model=PayoutOut)
def request_payout(
    combine_id: int,
    payload: PayoutIn | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> PayoutOut:
    """Request a payout on a FUNDED, ACTIVATED account: the trader's split
    (80/20 or 50/50) of FUNDED-STAGE realized profit, net of prior requests.
    Body is optional JSON {amount?: number}; absent → the full available
    amount. Simulated — records a 'payout_requested' event but moves no
    money. The booked amount DEBITS the funded balance at REQUEST time
    (services/combine_state — funds are held while the simulated review
    runs); the settle pass approves it after the review window by recording
    a matching 'payout_approved' (jobs/settle_combines).

    Policy gates (each a distinct 409): the PAYOUT_* minimums above — at
    least $125, within the available balance, 5 funded-stage winning days
    (realized ≥ +$150 in a 5pm-PT trading day), one request per 24h — and
    the post-debit balance must stay above the MLL floor.

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
    # Per-user throttle — a second belt over the idempotency window below: caps
    # how often one user can fire payout requests regardless of which combine, so
    # a scripted loop can't hammer the booking path across many accounts.
    enforce_user(financial_limiter, user.id, "payout")
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

    # Track-record gate: enough FUNDED-STAGE winning days (realized meets the
    # winning-day bar within a 5pm-PT trading day) since the accounting epoch.
    epoch = combine.funded_epoch_at or combine.funded_activated_at
    winning_days = sum(
        1
        for pnl in realized_by_trading_day(session, combine.id, epoch).values()
        if pnl >= PAYOUT_WINNING_DAY_PROFIT
    )
    if winning_days < PAYOUT_MIN_WINNING_DAYS:
        raise HTTPException(
            409,
            f"payouts unlock after {PAYOUT_MIN_WINNING_DAYS} winning days "
            f"(realized ≥ ${PAYOUT_WINNING_DAY_PROFIT:,.0f} in a day) on the "
            f"funded account — {winning_days} so far",
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
            CombineEvent.type.in_(PAYOUT_DEBIT_TYPES),
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

    # Pacing: at most one payout request per interval on this combine.
    interval_cutoff = now - timedelta(hours=PAYOUT_MIN_INTERVAL_H)
    paced = session.execute(
        select(CombineEvent.id)
        .where(
            CombineEvent.combine_id == combine.id,
            CombineEvent.type.in_(PAYOUT_DEBIT_TYPES),
            CombineEvent.created_at >= interval_cutoff,
        )
        .limit(1)
    ).scalar_one_or_none()
    if paced is not None:
        raise HTTPException(
            409,
            f"only one payout request per {PAYOUT_MIN_INTERVAL_H:,.0f} hours — "
            "try again later",
        )

    # `available` is read UNDER the lock so a racing request can't have booked
    # against the same balance without us seeing it.
    available = max(0.0, snap.payout_eligible - _payouts_requested(session, combine.id))
    if available <= 0:
        raise HTTPException(409, "no payout currently available")
    amount = available if payload is None or payload.amount is None else float(payload.amount)
    if amount > available + 1e-9:
        raise HTTPException(
            409,
            f"requested ${amount:,.2f} exceeds the ${available:,.2f} available payout",
        )
    if amount < PAYOUT_MIN_AMOUNT:
        raise HTTPException(
            409, f"minimum payout is ${PAYOUT_MIN_AMOUNT:,.0f}"
        )
    # The withdrawal debits the balance — it must stay ABOVE the MLL floor.
    if snap.balance - amount <= snap.mll:
        raise HTTPException(
            409,
            "payout would drop the balance to the Maximum Loss Limit — "
            "reduce the amount",
        )
    record_event(
        session,
        locked,
        "payout_requested",
        f"Payout requested — ${amount:,.2f} (pending review).",
        amount=amount,
    )
    session.commit()
    return PayoutOut(combine_id=combine.id, amount=amount, requested_at=now)


@router.post("/{combine_id}/activate-account", response_model=CombineOut)
def activate_account(
    combine_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> CombineOut:
    """Activate a funded account — one unified flow for both paths. Charges
    the $149 fee on the activation path and $0 on the no-activation path
    (simulated), records the activation event, and unlocks payouts. 409 if
    the account isn't funded, is already activated, or still has open or
    working trades. Activation stamps the funded-stage accounting EPOCH:
    the balance restarts at the tier start (realized-since-activation minus
    booked payouts), the HWM/MLL re-seed, and payout eligibility starts at
    0 — the profit used to PASS stays with the firm."""
    # Per-user throttle: activation charges a fee + writes a payment row.
    enforce_user(financial_limiter, user.id, "activation")
    combine = _owned_combine(session, user, combine_id)
    snap = combine_snapshot(session, combine)
    if not snap.funded:
        raise HTTPException(409, "account is not funded")
    if not snap.activation_required:
        raise HTTPException(409, "funded account is already activated")
    # Flat book required: the funded epoch counts trades opened at/after it,
    # so an open position's eventual P&L would straddle the two accountings.
    if has_open_book(session, combine.id):
        raise HTTPException(
            409,
            "close all open positions and cancel working orders before activating",
        )
    fee = pricing.activation_fee(combine.pricing_path)
    now = datetime.now(timezone.utc)
    tier = TIERS[combine.tier]
    combine.funded_activated_at = now
    combine.funded_epoch_at = now
    combine.hwm = tier.starting_balance
    combine.settled_hwm = tier.starting_balance
    # Treat the activation instant as the day's settlement so the next read
    # doesn't immediately log a spurious "settled" event.
    combine.last_settled_at = now
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
