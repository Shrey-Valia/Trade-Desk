"""Operator back office — /api/admin/*.

Every endpoint depends on services.auth.require_admin (router-wide); every
MUTATION writes an AdminAction audit row via services/admin_audit.audit in
the same transaction as the change. See
docs/P0_IMPLEMENTATION_PLAN_2026-07-14.md (workstream C2) for the contract.

Surface:
  * Users     — search/detail, suspend/unsuspend, promote/demote,
                grant-reset-credit, KYC decide.
  * Combines  — manual fail / unfail / extend_billing adjustments.
  * Payments  — refund (reuses the Stripe webhook's refund core).
  * Payouts   — the human review queue + approve/deny/hold/resume/mark-paid
                (delegating to services/payout_desk.decide).
  * Invites   — mint / list / revoke the codes that gate signup when
                settings.signup_require_invite is on (closed launch).
  * Platform  — the kill switch (trading mode + symbol ban list). DB-only,
                no market-data dependency: it works exactly when the feed
                is the thing that broke.
  * Metrics   — MRR, tier counts/pass rates, payout liability, user counts.
  * Jobs      — latest JobRun per scheduled job + staleness flags.
  * Actions   — the append-only AdminAction audit log (dispute answering).

PII discipline: no password hashes, no session tokens, no payout-method
details_json, no KYC dob/document fields — the detail view exposes only the
KYC legal_name + country alongside the provider decision.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from config import settings
from database import get_session
from models.admin_action import AdminAction
from models.combine import Combine
from models.combine_event import CombineEvent
from models.invite import Invite
from models.job_run import JobRun
from models.kyc import KycVerification
from models.payment import Payment
from models.payout_request import PAYOUT_STATES, PayoutRequest
from models.support_ticket import SupportTicket
from models.trade import Trade
from models.user import User

# The webhook's refund core is a clean module-level function (session, payment,
# event_type) with no Stripe coupling — reused directly rather than replicated
# so the admin refund can never drift from the chargeback path's ledger
# semantics (mark refunded + cancel working orders + archive the combine +
# repoint the active combine + 'refunded' combine_event + commit).
from routers.payments import _refund_payment
from services import platform_state, verification
from services.account_tiers import TIERS
from services.admin_audit import audit
from services.auth import require_admin
from services.combine_state import (
    PAYOUT_CREDIT_TYPES,
    PAYOUT_DEBIT_TYPES,
    combine_snapshot,
    record_event,
)
from services.invites import (
    INVITE_STATES,
    expiry_from_days,
    invite_status,
    mint_code,
)
from services.payout_desk import decide as payout_decide
from services.platform_state import TRADING_MODES
from services.pricing import BASE_MONTHLY, RESET_CREDIT_CAP, monthly_price
from services.verification import decide_kyc

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, f"user_not_found: user {user_id} not found")
    return user


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


# The product's home timezone — same convention as the 5pm-PT settlement
# boundary in services/combine_settlement.
_PT = ZoneInfo("America/Los_Angeles")


# ---------------------------------------------------------------------------
# Users — search / detail
# ---------------------------------------------------------------------------


class AdminUserItem(BaseModel):
    id: int
    email: str
    display_name: str | None
    role: str
    suspended_at: datetime | None
    created_at: datetime
    reset_credits: int
    # Combine counts by lifecycle status, e.g. {"active": 2, "archived": 1}.
    combines: dict[str, int]
    # "unverified" | "pending" | "verified" | "rejected"
    kyc_status: str


class AdminUsersPage(BaseModel):
    items: list[AdminUserItem]
    total: int
    page: int


@router.get("/users", response_model=AdminUsersPage)
def list_users(
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_session),
) -> AdminUsersPage:
    """Search users by email / display name (case-insensitive substring),
    newest first, paginated. Combine counts and KYC statuses are batched
    (two grouped queries for the whole page — no per-row N+1)."""
    stmt = select(User)
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(User.email.ilike(like), User.display_name.ilike(like))
        )
    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(User.created_at.desc(), User.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    ids = [u.id for u in rows]
    combine_counts: dict[int, dict[str, int]] = {}
    kyc_map: dict[int, str] = {}
    if ids:
        for uid, status, n in db.execute(
            select(Combine.user_id, Combine.status, func.count())
            .where(Combine.user_id.in_(ids))
            .group_by(Combine.user_id, Combine.status)
        ):
            combine_counts.setdefault(uid, {})[status] = int(n)
        for uid, status in db.execute(
            select(KycVerification.user_id, KycVerification.status).where(
                KycVerification.user_id.in_(ids)
            )
        ):
            kyc_map[uid] = status
    return AdminUsersPage(
        items=[
            AdminUserItem(
                id=u.id,
                email=u.email,
                display_name=u.display_name,
                role=u.role,
                suspended_at=u.suspended_at,
                created_at=u.created_at,
                reset_credits=u.reset_credits,
                combines=combine_counts.get(u.id, {}),
                kyc_status=kyc_map.get(u.id, "unverified"),
            )
            for u in rows
        ],
        total=int(total),
        page=page,
    )


class AdminCombineOut(BaseModel):
    id: int
    tier: str
    name: str
    account_code: str
    status: str
    outcome: str
    hwm: float
    settled_hwm: float
    funded_at: datetime | None
    funded_activated_at: datetime | None
    funded_epoch_at: datetime | None
    eval_reset_at: datetime | None
    pricing_path: str
    profit_split: float
    paid_through: datetime | None
    cancel_at_period_end: bool
    created_at: datetime


class AdminPaymentOut(BaseModel):
    id: int
    combine_id: int | None
    tier: str
    amount: float
    status: str
    created_at: datetime


class AdminEventOut(BaseModel):
    id: int
    combine_id: int
    type: str
    message: str
    amount: float | None
    created_at: datetime


class AdminTicketSummaryOut(BaseModel):
    id: int
    category: str
    subject: str
    status: str
    created_at: datetime


class AdminPayoutRequestOut(BaseModel):
    id: int
    user_id: int
    combine_id: int
    amount: float
    state: str
    reason_code: str | None
    note: str | None
    reviewer_id: int | None
    requested_at: datetime
    decided_at: datetime | None


class AdminKycOut(BaseModel):
    status: str
    provider: str
    reject_reason: str | None
    # From the declared identity — deliberately ONLY these two fields; the
    # dob / document_type stay server-side.
    legal_name: str | None
    country: str | None
    submitted_at: datetime
    decided_at: datetime | None


class AdminPayoutMethodOut(BaseModel):
    # Exactly verification.masked_method's shape — details_json never leaves
    # the server.
    id: int
    type: str
    label: str
    is_default: bool
    created_at: datetime


class AdminUserDetail(BaseModel):
    id: int
    email: str
    display_name: str | None
    role: str
    suspended_at: datetime | None
    created_at: datetime
    reset_credits: int
    active_combine_id: int | None
    combines: list[AdminCombineOut]
    payments: list[AdminPaymentOut]
    events: list[AdminEventOut]
    tickets: list[AdminTicketSummaryOut]
    payout_requests: list[AdminPayoutRequestOut]
    kyc: AdminKycOut | None
    payout_methods: list[AdminPayoutMethodOut]


def _payout_request_out(row: PayoutRequest) -> AdminPayoutRequestOut:
    return AdminPayoutRequestOut(
        id=row.id,
        user_id=row.user_id,
        combine_id=row.combine_id,
        amount=float(row.amount or 0.0),
        state=row.state,
        reason_code=row.reason_code,
        note=row.note,
        reviewer_id=row.reviewer_id,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def user_detail(
    user_id: int,
    db: Session = Depends(get_session),
) -> AdminUserDetail:
    user = _get_user_or_404(db, user_id)
    combines = (
        db.execute(
            select(Combine)
            .where(Combine.user_id == user.id)
            .order_by(Combine.created_at.desc(), Combine.id.desc())
        )
        .scalars()
        .all()
    )
    payments = (
        db.execute(
            select(Payment)
            .where(Payment.user_id == user.id)
            .order_by(Payment.created_at.desc(), Payment.id.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    events = (
        db.execute(
            select(CombineEvent)
            .where(CombineEvent.user_id == user.id)
            .order_by(CombineEvent.created_at.desc(), CombineEvent.id.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    tickets = (
        db.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == user.id)
            .order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc())
        )
        .scalars()
        .all()
    )
    payout_requests = (
        db.execute(
            select(PayoutRequest)
            .where(PayoutRequest.user_id == user.id)
            .order_by(PayoutRequest.requested_at.desc(), PayoutRequest.id.desc())
        )
        .scalars()
        .all()
    )
    kyc_row = verification.get_kyc(db, user)
    kyc_out: AdminKycOut | None = None
    if kyc_row is not None:
        try:
            declared = json.loads(kyc_row.submitted_json or "{}")
        except (ValueError, TypeError):
            declared = {}
        kyc_out = AdminKycOut(
            status=kyc_row.status,
            provider=kyc_row.provider,
            reject_reason=kyc_row.reject_reason,
            legal_name=declared.get("legal_name"),
            country=declared.get("country"),
            submitted_at=kyc_row.submitted_at,
            decided_at=kyc_row.decided_at,
        )
    return AdminUserDetail(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        suspended_at=user.suspended_at,
        created_at=user.created_at,
        reset_credits=user.reset_credits,
        active_combine_id=user.active_combine_id,
        combines=[
            AdminCombineOut(
                id=c.id,
                tier=c.tier,
                name=c.name,
                account_code=c.account_code,
                status=c.status,
                outcome=c.outcome,
                hwm=float(c.hwm),
                settled_hwm=float(c.settled_hwm),
                funded_at=c.funded_at,
                funded_activated_at=c.funded_activated_at,
                funded_epoch_at=c.funded_epoch_at,
                eval_reset_at=c.eval_reset_at,
                pricing_path=c.pricing_path,
                profit_split=c.profit_split,
                paid_through=c.paid_through,
                cancel_at_period_end=c.cancel_at_period_end,
                created_at=c.created_at,
            )
            for c in combines
        ],
        payments=[
            AdminPaymentOut(
                id=p.id,
                combine_id=p.combine_id,
                tier=p.tier,
                amount=float(p.amount or 0.0),
                status=p.status,
                created_at=p.created_at,
            )
            for p in payments
        ],
        events=[
            AdminEventOut(
                id=e.id,
                combine_id=e.combine_id,
                type=e.type,
                message=e.message,
                amount=float(e.amount) if e.amount is not None else None,
                created_at=e.created_at,
            )
            for e in events
        ],
        tickets=[
            AdminTicketSummaryOut(
                id=t.id,
                category=t.category,
                subject=t.subject,
                status=t.status,
                created_at=t.created_at,
            )
            for t in tickets
        ],
        payout_requests=[_payout_request_out(r) for r in payout_requests],
        kyc=kyc_out,
        payout_methods=[
            AdminPayoutMethodOut(**m) for m in verification.list_methods(db, user)
        ],
    )


# ---------------------------------------------------------------------------
# Users — mutations
# ---------------------------------------------------------------------------


class ReasonIn(BaseModel):
    reason: str = Field(..., max_length=300)

    @field_validator("reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason must be non-empty")
        return v


class OptionalReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class UserStateOut(BaseModel):
    id: int
    role: str
    suspended_at: datetime | None
    reset_credits: int


def _user_state(user: User) -> UserStateOut:
    return UserStateOut(
        id=user.id,
        role=user.role,
        suspended_at=user.suspended_at,
        reset_credits=user.reset_credits,
    )


@router.post("/users/{user_id}/suspend", response_model=UserStateOut)
def suspend_user(
    user_id: int,
    payload: ReasonIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> UserStateOut:
    target = _get_user_or_404(db, user_id)
    if target.id == admin.id:
        raise HTTPException(
            422, "cannot_suspend_self: you cannot suspend your own account"
        )
    if target.suspended_at is not None:
        raise HTTPException(409, "already_suspended: user is already suspended")
    before = {"suspended_at": None}
    target.suspended_at = datetime.now(timezone.utc)
    audit(
        db,
        admin,
        "user.suspend",
        "user",
        target.id,
        before=before,
        after={"suspended_at": _iso(target.suspended_at)},
        reason=payload.reason,
    )
    db.commit()
    return _user_state(target)


@router.post("/users/{user_id}/unsuspend", response_model=UserStateOut)
def unsuspend_user(
    user_id: int,
    payload: OptionalReasonIn | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> UserStateOut:
    target = _get_user_or_404(db, user_id)
    if target.suspended_at is None:
        raise HTTPException(409, "not_suspended: user is not suspended")
    before = {"suspended_at": _iso(target.suspended_at)}
    target.suspended_at = None
    audit(
        db,
        admin,
        "user.unsuspend",
        "user",
        target.id,
        before=before,
        after={"suspended_at": None},
        reason=payload.reason if payload else None,
    )
    db.commit()
    return _user_state(target)


@router.post("/users/{user_id}/promote", response_model=UserStateOut)
def promote_user(
    user_id: int,
    payload: OptionalReasonIn | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> UserStateOut:
    target = _get_user_or_404(db, user_id)
    if target.role == "admin":
        raise HTTPException(409, "already_admin: user is already an admin")
    target.role = "admin"
    audit(
        db,
        admin,
        "user.promote",
        "user",
        target.id,
        before={"role": "trader"},
        after={"role": "admin"},
        reason=payload.reason if payload else None,
    )
    db.commit()
    return _user_state(target)


@router.post("/users/{user_id}/demote", response_model=UserStateOut)
def demote_user(
    user_id: int,
    payload: OptionalReasonIn | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> UserStateOut:
    target = _get_user_or_404(db, user_id)
    if target.id == admin.id:
        # The last-admin lockout guard's common face: since the actor is
        # always an admin, the only demotion that could zero the admin count
        # is a self-demotion — refused outright.
        raise HTTPException(
            422, "cannot_demote_self: you cannot demote your own account"
        )
    if target.role != "admin":
        raise HTTPException(409, "not_admin: user is not an admin")
    # Defensive belt-and-suspenders: never allow the platform to reach zero
    # admins even if the actor's own role changed mid-request.
    admin_count = db.execute(
        select(func.count()).select_from(User).where(User.role == "admin")
    ).scalar_one()
    if int(admin_count) <= 1:
        raise HTTPException(
            409, "last_admin: demoting this user would leave zero admins"
        )
    target.role = "trader"
    audit(
        db,
        admin,
        "user.demote",
        "user",
        target.id,
        before={"role": "admin"},
        after={"role": "trader"},
        reason=payload.reason if payload else None,
    )
    db.commit()
    return _user_state(target)


class GrantCreditIn(BaseModel):
    count: int = Field(default=1, ge=1)
    reason: str = Field(..., max_length=300)

    @field_validator("reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason must be non-empty")
        return v


class GrantCreditOut(BaseModel):
    id: int
    reset_credits: int
    granted: int


@router.post("/users/{user_id}/grant-reset-credit", response_model=GrantCreditOut)
def grant_reset_credit(
    user_id: int,
    payload: GrantCreditIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> GrantCreditOut:
    """Grant free evaluation-reset credits, clamped to the same
    pricing.RESET_CREDIT_CAP the monthly-rebill banking respects — an
    operator grant can't stockpile past what billing itself allows."""
    target = _get_user_or_404(db, user_id)
    before = int(target.reset_credits or 0)
    new = min(before + payload.count, RESET_CREDIT_CAP)
    if new == before:
        raise HTTPException(
            409,
            f"reset_credit_cap_reached: user already holds the maximum "
            f"{RESET_CREDIT_CAP} reset credits",
        )
    target.reset_credits = new
    audit(
        db,
        admin,
        "user.grant_reset_credit",
        "user",
        target.id,
        before={"reset_credits": before},
        after={"reset_credits": new},
        reason=payload.reason,
    )
    db.commit()
    return GrantCreditOut(id=target.id, reset_credits=new, granted=new - before)


class KycDecideIn(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=160)


class KycDecideOut(BaseModel):
    user_id: int
    status: str
    reject_reason: str | None
    decided_at: datetime | None


@router.post("/users/{user_id}/kyc/decide", response_model=KycDecideOut)
def kyc_decide(
    user_id: int,
    payload: KycDecideIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> KycDecideOut:
    """Human KYC decision — delegates to verification.decide_kyc (which owns
    the state machine), stages the audit row, then commits both together so a
    crash can't land the decision with no audit trail."""
    before_status = db.execute(
        select(KycVerification.status).where(KycVerification.user_id == user_id)
    ).scalar_one_or_none()
    # commit=False: the decision stays uncommitted until the audit row is staged,
    # so the single db.commit() below lands both atomically.
    row = decide_kyc(db, user_id, payload.approve, payload.reason, commit=False)
    audit(
        db,
        admin,
        "user.kyc_decide",
        "user",
        user_id,
        before={"kyc_status": before_status},
        after={"kyc_status": row.status, "reject_reason": row.reject_reason},
        reason=payload.reason,
    )
    db.commit()
    return KycDecideOut(
        user_id=user_id,
        status=row.status,
        reject_reason=row.reject_reason,
        decided_at=row.decided_at,
    )


# ---------------------------------------------------------------------------
# Combines — manual adjustments
# ---------------------------------------------------------------------------


class CombineAdjustIn(BaseModel):
    action: str = Field(..., description="fail | unfail | extend_billing")
    reason: str = Field(..., max_length=300)
    days: int | None = Field(default=None, ge=1, le=90)

    @field_validator("reason")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason must be non-empty")
        return v


class CombineAdjustOut(BaseModel):
    id: int
    status: str
    outcome: str
    paid_through: datetime | None


@router.post("/combines/{combine_id}/adjust", response_model=CombineAdjustOut)
def adjust_combine(
    combine_id: int,
    payload: CombineAdjustIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> CombineAdjustOut:
    """Manual combine adjustment. `fail` mirrors the engine's MLL-breach
    path (services/combine_state.combine_snapshot): outcome flips to
    'failed' (status untouched — lifecycle stays orthogonal) plus a
    combine_events 'failed' row; `unfail` restores outcome AND status to
    'active'; `extend_billing` pushes paid_through by `days`."""
    if payload.action not in ("fail", "unfail", "extend_billing"):
        raise HTTPException(
            422,
            "unknown_action: action must be one of fail, unfail, extend_billing",
        )
    combine = db.get(Combine, combine_id)
    if combine is None:
        raise HTTPException(
            404, f"combine_not_found: combine {combine_id} not found"
        )

    if payload.action == "fail":
        if combine.outcome == "failed":
            raise HTTPException(409, "already_failed: combine is already failed")
        before = {"outcome": combine.outcome, "status": combine.status}
        combine.outcome = "failed"
        record_event(
            db,
            combine,
            "failed",
            "Evaluation failed — manual action by operator.",
        )
        audit(
            db,
            admin,
            "combine.fail",
            "combine",
            combine.id,
            before=before,
            after={"outcome": "failed", "status": combine.status},
            reason=payload.reason,
        )
    elif payload.action == "unfail":
        # Archived combines (refund / chargeback / subscription end) are
        # lifecycle-terminal — unfail must never resurrect one into the
        # active slot pool.
        if combine.status == "archived":
            raise HTTPException(
                409,
                "combine_archived: refund/archival owns the lifecycle — "
                "unfail cannot resurrect an archived combine",
            )
        if combine.outcome != "failed":
            raise HTTPException(409, "not_failed: combine is not failed")
        before = {"outcome": combine.outcome, "status": combine.status}
        combine.outcome = "active"
        record_event(
            db,
            combine,
            "unfailed",
            "Evaluation restored to active — manual action by operator.",
        )
        audit(
            db,
            admin,
            "combine.unfail",
            "combine",
            combine.id,
            before=before,
            after={"outcome": "active", "status": combine.status},
            reason=payload.reason,
        )
        db.commit()
        # HONESTY CHECK: the settle pass re-runs the engine within 5 minutes,
        # and if the balance still sits at/through the MLL floor it will
        # simply re-fail the combine — silently discarding the operator's
        # decision. Run the engine NOW and say so: both the unfail and the
        # engine's re-fail are already recorded (events + audit), so the 409
        # is informative, not a rollback.
        snap = combine_snapshot(db, combine)
        if snap.outcome == "failed":
            raise HTTPException(
                409,
                "still_breached: the engine immediately re-failed this "
                "combine (balance at/through the MLL floor). The unfail and "
                "re-fail are both recorded — adjust the balance basis before "
                "unfailing.",
            )
    else:  # extend_billing
        if payload.days is None:
            raise HTTPException(
                422, "days_required: extend_billing requires days (1-90)"
            )
        before = {"paid_through": _iso(combine.paid_through)}
        base = combine.paid_through or datetime.now(timezone.utc)
        combine.paid_through = _aware(base) + timedelta(days=payload.days)
        audit(
            db,
            admin,
            "combine.extend_billing",
            "combine",
            combine.id,
            before=before,
            after={"paid_through": _iso(combine.paid_through)},
            reason=payload.reason,
        )

    db.commit()
    db.refresh(combine)
    return CombineAdjustOut(
        id=combine.id,
        status=combine.status,
        outcome=combine.outcome,
        paid_through=combine.paid_through,
    )


# ---------------------------------------------------------------------------
# Payments — refund
# ---------------------------------------------------------------------------


class RefundOut(BaseModel):
    id: int
    status: str
    combine_id: int | None
    combine_status: str | None


@router.post("/payments/{payment_id}/refund", response_model=RefundOut)
def refund_payment(
    payment_id: int,
    payload: ReasonIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> RefundOut:
    """Operator refund — same ledger semantics as a Stripe charge.refunded
    webhook: the payment flips to 'refunded' and the combine it bought is
    archived (working orders cancelled, active combine repointed, 'refunded'
    combine_event booked). The audit row is staged BEFORE the shared refund
    core runs so its commit lands both atomically."""
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(
            404, f"payment_not_found: payment {payment_id} not found"
        )
    if payment.status == "refunded":
        raise HTTPException(409, "already_refunded: payment is already refunded")
    if payment.status == "migration_grant":
        raise HTTPException(
            409, "not_refundable: migration grants carry no money to refund"
        )
    audit(
        db,
        admin,
        "payment.refund",
        "payment",
        payment.id,
        before={"status": payment.status},
        after={"status": "refunded"},
        reason=payload.reason,
    )
    # Reuse of routers/payments._refund_payment (the webhook core). It
    # commits — landing the staged audit row in the same transaction.
    _refund_payment(db, payment, "charge.refunded")
    combine = (
        db.get(Combine, payment.combine_id)
        if payment.combine_id is not None
        else None
    )
    return RefundOut(
        id=payment.id,
        status=payment.status,
        combine_id=payment.combine_id,
        combine_status=combine.status if combine is not None else None,
    )


# ---------------------------------------------------------------------------
# Payout review queue
# ---------------------------------------------------------------------------

# The states a reviewer can still act on — the default queue view.
_ACTIONABLE_PAYOUT_STATES = ("requested", "under_review", "held")


class PayoutQueueItem(BaseModel):
    id: int
    user_id: int
    user_email: str
    combine_id: int
    tier: str
    account_code: str
    amount: float
    state: str
    reason_code: str | None
    note: str | None
    reviewer_id: int | None
    requested_at: datetime
    decided_at: datetime | None
    # Reviewer context — realized-basis account snapshot (starting balance +
    # epoch-scoped realized P&L − net booked payout debits) plus the user's
    # payout history and account age.
    starting_balance: float
    balance: float
    total_approved_payouts: float
    days_since_funded: int | None  # PT calendar days (America/Los_Angeles)


class PayoutQueueOut(BaseModel):
    items: list[PayoutQueueItem]
    total: int


@router.get("/payouts", response_model=PayoutQueueOut)
def payout_queue(
    state: str | None = None,
    db: Session = Depends(get_session),
) -> PayoutQueueOut:
    """The review queue. Default view: the actionable states
    (requested / under_review / held), oldest first — FIFO review order.
    Context is batched: one query each for the requests, the trades, the
    payout ledger events, and the per-user approved totals."""
    if state is not None and state not in PAYOUT_STATES:
        raise HTTPException(
            422,
            "unknown_state: state must be one of " + ", ".join(PAYOUT_STATES),
        )
    states = (state,) if state is not None else _ACTIONABLE_PAYOUT_STATES
    rows = db.execute(
        select(PayoutRequest, User.email, Combine)
        .join(User, User.id == PayoutRequest.user_id)
        .join(Combine, Combine.id == PayoutRequest.combine_id)
        .where(PayoutRequest.state.in_(states))
        .order_by(PayoutRequest.requested_at.asc(), PayoutRequest.id.asc())
    ).all()

    combine_ids = {c.id for _req, _email, c in rows}
    user_ids = {req.user_id for req, _email, _c in rows}

    # Batched context (mirrors combine_state.realized_sum_for_combine /
    # payouts_booked semantics; the per-combine `since` filter is applied in
    # Python because each combine's epoch differs).
    trades_by_combine: dict[int, list[tuple[datetime | None, float]]] = {}
    if combine_ids:
        for cid, entry_date, pnl in db.execute(
            select(Trade.combine_id, Trade.entry_date, Trade.realized_pnl).where(
                Trade.combine_id.in_(combine_ids),
                Trade.status == "closed",
                Trade.origin == "execution",
            )
        ):
            trades_by_combine.setdefault(cid, []).append(
                (entry_date, float(pnl or 0.0))
            )
    events_by_combine: dict[int, list[tuple[str, float, datetime | None]]] = {}
    if combine_ids:
        for cid, type_, amount, created_at in db.execute(
            select(
                CombineEvent.combine_id,
                CombineEvent.type,
                CombineEvent.amount,
                CombineEvent.created_at,
            ).where(
                CombineEvent.combine_id.in_(combine_ids),
                CombineEvent.type.in_(PAYOUT_DEBIT_TYPES + PAYOUT_CREDIT_TYPES),
            )
        ):
            events_by_combine.setdefault(cid, []).append(
                (type_, float(amount or 0.0), created_at)
            )
    approved_by_user: dict[int, float] = {}
    if user_ids:
        for uid, total in db.execute(
            select(
                PayoutRequest.user_id,
                func.coalesce(func.sum(PayoutRequest.amount), 0.0),
            )
            .where(
                PayoutRequest.user_id.in_(user_ids),
                PayoutRequest.state.in_(("approved", "paid")),
            )
            .group_by(PayoutRequest.user_id)
        ):
            approved_by_user[uid] = float(total or 0.0)

    now = datetime.now(timezone.utc)
    items: list[PayoutQueueItem] = []
    for req, email, combine in rows:
        tier = TIERS.get(combine.tier)
        starting = tier.starting_balance if tier is not None else 0.0
        since = combine.funded_epoch_at or combine.eval_reset_at
        realized = sum(
            pnl
            for entry, pnl in trades_by_combine.get(combine.id, [])
            if since is None or (entry is not None and _aware(entry) >= _aware(since))
        )
        payout_since = combine.funded_epoch_at
        net_payouts = 0.0
        for type_, amount, created_at in events_by_combine.get(combine.id, []):
            if payout_since is not None and (
                created_at is None or _aware(created_at) < _aware(payout_since)
            ):
                continue
            net_payouts += amount if type_ in PAYOUT_DEBIT_TYPES else -amount
        net_payouts = max(0.0, net_payouts)
        items.append(
            PayoutQueueItem(
                **_payout_request_out(req).model_dump(),
                user_email=email,
                tier=combine.tier,
                account_code=combine.account_code,
                starting_balance=starting,
                balance=round(starting + realized - net_payouts, 2),
                total_approved_payouts=round(approved_by_user.get(req.user_id, 0.0), 2),
                # PT calendar days, not elapsed-24h periods: timedelta.days
                # would under-report by one until the funding hour passes
                # each day (funded at noon reads "5 days" all morning of
                # day 6).
                days_since_funded=(
                    max(
                        0,
                        (
                            now.astimezone(_PT).date()
                            - _aware(combine.funded_at).astimezone(_PT).date()
                        ).days,
                    )
                    if combine.funded_at is not None
                    else None
                ),
            )
        )
    return PayoutQueueOut(items=items, total=len(items))


class PayoutDecisionIn(BaseModel):
    reason_code: str | None = None
    note: str | None = Field(default=None, max_length=300)


# URL segment → payout_desk.decide action.
_PAYOUT_DECISIONS = {
    "approve": "approve",
    "deny": "deny",
    "hold": "hold",
    "resume": "resume_review",
    "mark-paid": "mark_paid",
}


@router.post("/payouts/{request_id}/{decision}", response_model=AdminPayoutRequestOut)
def decide_payout(
    request_id: int,
    decision: str,
    payload: PayoutDecisionIn | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> AdminPayoutRequestOut:
    """One reviewer action, delegated to services/payout_desk.decide with
    reviewer_id = the acting admin. The desk owns the state machine and the
    ledger events; its 404/409/422 surface as-is (deny without a valid
    reason_code is its 422). The audit row lands after a successful
    decision — a refused transition mutates nothing and audits nothing."""
    action = _PAYOUT_DECISIONS.get(decision)
    if action is None:
        raise HTTPException(
            422,
            "unknown_decision: decision must be one of "
            + ", ".join(sorted(_PAYOUT_DECISIONS)),
        )
    body = payload or PayoutDecisionIn()
    before_row = db.get(PayoutRequest, request_id)
    before_state = before_row.state if before_row is not None else None
    # commit=False: the decision stays uncommitted until the audit row is staged,
    # so the single db.commit() below lands both atomically — no window where a
    # crash leaves the payout decided with no audit trail.
    updated = payout_decide(
        db,
        request_id,
        action,
        reviewer_id=admin.id,
        reason_code=body.reason_code,
        note=body.note,
        commit=False,
    )
    audit(
        db,
        admin,
        f"payout.{action}",
        "payout_request",
        updated.id,
        before={"state": before_state},
        after={"state": updated.state, "reason_code": updated.reason_code},
        reason=body.note or body.reason_code,
    )
    db.commit()
    return _payout_request_out(updated)


# ---------------------------------------------------------------------------
# Invites — the closed-launch signup gate
# ---------------------------------------------------------------------------


class InviteOut(BaseModel):
    id: int
    code: str
    email: str | None
    note: str | None
    # Derived (services/invites.invite_status), never stored.
    status: str
    created_by_email: str | None
    created_at: str
    expires_at: str | None
    redeemed_at: str | None
    redeemed_by_email: str | None
    revoked_at: str | None


class InvitesPage(BaseModel):
    invites: list[InviteOut]
    total: int
    page: int
    # Echoed so the console can explain WHY signup is (or isn't) gated
    # without a second round trip to a settings endpoint.
    require_invite: bool
    default_ttl_days: float


class CreateInviteIn(BaseModel):
    # Bind the code to one address, or leave blank for a bearer code.
    email: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=200)
    # None = fall back to settings.invite_default_ttl_days; 0 = never expires.
    expires_in_days: float | None = Field(default=None, ge=0, le=365)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if not v:
            return None
        # Same light shape check as routers/auth._normalize_email — a typo'd
        # binding silently locks the invitee out, so catch it at mint time.
        if "@" not in v or " " in v:
            raise ValueError("invalid email address")
        return v

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


def _invite_out(inv: Invite, emails: dict[int, str]) -> InviteOut:
    return InviteOut(
        id=inv.id,
        code=inv.code,
        email=inv.email,
        note=inv.note,
        status=invite_status(inv),
        created_by_email=emails.get(inv.created_by_id),
        created_at=_iso(inv.created_at) or "",
        expires_at=_iso(inv.expires_at),
        redeemed_at=_iso(inv.redeemed_at),
        redeemed_by_email=(
            emails.get(inv.redeemed_by_id) if inv.redeemed_by_id else None
        ),
        revoked_at=_iso(inv.revoked_at),
    )


def _invite_emails(db: Session, rows: list[Invite]) -> dict[int, str]:
    """One batched lookup of every creator/redeemer email on the page —
    the same no-N+1 discipline as the user list above."""
    ids = {inv.created_by_id for inv in rows}
    ids |= {inv.redeemed_by_id for inv in rows if inv.redeemed_by_id is not None}
    if not ids:
        return {}
    return {
        uid: email
        for uid, email in db.execute(
            select(User.id, User.email).where(User.id.in_(ids))
        ).all()
    }


@router.get("/invites", response_model=InvitesPage)
def list_invites(
    status: str | None = Query(default=None),
    q: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_session),
) -> InvitesPage:
    """The invite ledger, newest first, paginated. Optional status filter
    plus a case-insensitive search over code / bound email / note.

    Status is derived, so it can't be a SQL WHERE on a column: expiry is
    filtered with an explicit timestamp predicate and the terminal states
    with NULL checks, keeping the filter in the database rather than
    post-filtering a page (which would return short pages).
    """
    if status is not None and status not in INVITE_STATES:
        raise HTTPException(
            422, f"invalid_status: status must be one of {', '.join(INVITE_STATES)}"
        )
    now = datetime.now(timezone.utc)
    stmt = select(Invite)
    if status == "redeemed":
        stmt = stmt.where(Invite.redeemed_at.is_not(None))
    elif status == "revoked":
        stmt = stmt.where(
            Invite.redeemed_at.is_(None), Invite.revoked_at.is_not(None)
        )
    elif status == "expired":
        stmt = stmt.where(
            Invite.redeemed_at.is_(None),
            Invite.revoked_at.is_(None),
            Invite.expires_at.is_not(None),
            Invite.expires_at <= now,
        )
    elif status == "active":
        stmt = stmt.where(
            Invite.redeemed_at.is_(None),
            Invite.revoked_at.is_(None),
            or_(Invite.expires_at.is_(None), Invite.expires_at > now),
        )
    needle = q.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                Invite.code.ilike(like),
                Invite.email.ilike(like),
                Invite.note.ilike(like),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(Invite.created_at.desc(), Invite.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    emails = _invite_emails(db, list(rows))
    return InvitesPage(
        invites=[_invite_out(inv, emails) for inv in rows],
        total=int(total),
        page=page,
        require_invite=settings.signup_require_invite,
        default_ttl_days=settings.invite_default_ttl_days,
    )


@router.post("/invites", response_model=InviteOut, status_code=201)
def create_invite(
    payload: CreateInviteIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> InviteOut:
    """Mint a code. Bound to an email or bearer; expiring per the request
    or the configured default."""
    if payload.email is not None:
        taken = db.execute(
            select(User.id).where(User.email == payload.email)
        ).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(
                409,
                "already_registered: that email already has an account",
            )
    ttl = (
        payload.expires_in_days
        if payload.expires_in_days is not None
        else settings.invite_default_ttl_days
    )
    inv = Invite(
        code=mint_code(db),
        email=payload.email,
        note=payload.note,
        created_by_id=admin.id,
        expires_at=expiry_from_days(ttl),
    )
    db.add(inv)
    db.flush()
    audit(
        db,
        admin,
        "invite.create",
        "invite",
        inv.id,
        after={
            "code": inv.code,
            "email": inv.email,
            "expires_at": _iso(inv.expires_at),
        },
        reason=inv.note,
    )
    db.commit()
    db.refresh(inv)
    return _invite_out(inv, {admin.id: admin.email})


@router.post("/invites/{invite_id}/revoke", response_model=InviteOut)
def revoke_invite(
    invite_id: int,
    payload: OptionalReasonIn | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> InviteOut:
    """Kill an unredeemed code. Redemption is terminal — a redeemed invite
    can't be revoked (the account it created already exists; suspend the
    user instead)."""
    inv = db.get(Invite, invite_id)
    if inv is None:
        raise HTTPException(404, "invite not found")
    status = invite_status(inv)
    if status == "redeemed":
        raise HTTPException(
            409,
            "already_redeemed: that invite was already used — suspend the "
            "account instead",
        )
    if status == "revoked":
        raise HTTPException(409, "already_revoked: that invite is already revoked")
    inv.revoked_at = datetime.now(timezone.utc)
    inv.revoked_by_id = admin.id
    audit(
        db,
        admin,
        "invite.revoke",
        "invite",
        inv.id,
        before={"status": status},
        after={"status": "revoked", "revoked_at": _iso(inv.revoked_at)},
        reason=payload.reason if payload else None,
    )
    db.commit()
    db.refresh(inv)
    emails = _invite_emails(db, [inv])
    return _invite_out(inv, emails)


# ---------------------------------------------------------------------------
# Platform — the kill switch
# ---------------------------------------------------------------------------


class PlatformOut(BaseModel):
    trading_mode: str
    banned_symbols: list[str]
    zero_dte_universe: list[str]
    enforce_tradeable_universe: bool


def _platform_out(db: Session) -> PlatformOut:
    status = platform_state.platform_status(db)
    return PlatformOut(
        trading_mode=status["trading_mode"],
        banned_symbols=status["banned_symbols"],
        zero_dte_universe=[s.upper() for s in settings.zero_dte_universe],
        enforce_tradeable_universe=settings.enforce_tradeable_universe,
    )


@router.get("/platform", response_model=PlatformOut)
def get_platform(db: Session = Depends(get_session)) -> PlatformOut:
    return _platform_out(db)


class PlatformIn(BaseModel):
    trading_mode: str | None = None
    banned_symbols: list[str] | None = None
    reason: str | None = Field(default=None, max_length=300)


@router.put("/platform", response_model=PlatformOut)
def set_platform(
    payload: PlatformIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_session),
) -> PlatformOut:
    """The operator kill switch. Deliberately DB-only (platform_state KV +
    settings reads) — NO market-data dependency, so halting trading works
    exactly when the data feed is the thing that broke."""
    if payload.trading_mode is None and payload.banned_symbols is None:
        raise HTTPException(
            400, "nothing_to_update: provide trading_mode and/or banned_symbols"
        )
    if payload.trading_mode is not None and payload.trading_mode not in TRADING_MODES:
        raise HTTPException(
            422,
            "unknown_trading_mode: trading_mode must be one of "
            + ", ".join(TRADING_MODES),
        )
    before = platform_state.platform_status(db)
    # Stage both keys AND the audit row without committing, then land them in
    # ONE commit below. This makes the flip atomic with its audit trail: a
    # crash mid-request lands neither, and a combined {mode, symbols} PUT can
    # never half-apply. (commit=False overrides platform_state's default
    # commit-per-key behavior, which exists for the standalone-flip case.)
    if payload.trading_mode is not None:
        platform_state.set_trading_mode(db, payload.trading_mode, commit=False)
    if payload.banned_symbols is not None:
        platform_state.set_banned_symbols(db, payload.banned_symbols, commit=False)
    # Flush the staged writes so the audit `after` snapshot (read back via
    # platform_status) reflects the pending change even though nothing has
    # committed yet — the session isn't autoflushed on read here.
    db.flush()
    after = platform_state.platform_status(db)
    audit(
        db,
        admin,
        "platform.update",
        "platform",
        None,
        before=before,
        after=after,
        reason=payload.reason,
    )
    db.commit()
    return _platform_out(db)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TierCombineCounts(BaseModel):
    by_status: dict[str, int]
    by_outcome: dict[str, int]


class MetricsOut(BaseModel):
    mrr: float
    combines: dict[str, TierCombineCounts]
    # funded / (funded + failed) among terminal outcomes; None when no
    # combine of the tier has reached a terminal outcome yet.
    pass_rate: dict[str, float | None]
    payout_liability: dict[str, float]
    users_total: int
    users_last_30d: int
    tickets_open: int


@router.get("/metrics", response_model=MetricsOut)
def metrics(db: Session = Depends(get_session)) -> MetricsOut:
    # MRR: sum of each ACTIVE (non-archived) combine's monthly price at its
    # own pricing path + split (services/pricing is the source of truth).
    mrr = 0.0
    for tier, path, split, n in db.execute(
        select(
            Combine.tier, Combine.pricing_path, Combine.profit_split, func.count()
        )
        .where(Combine.status != "archived")
        .group_by(Combine.tier, Combine.pricing_path, Combine.profit_split)
    ):
        if tier in BASE_MONTHLY:
            mrr += monthly_price(tier, path, float(split or 0.8)) * int(n)

    combines: dict[str, TierCombineCounts] = {}
    for tier, status, outcome, n in db.execute(
        select(Combine.tier, Combine.status, Combine.outcome, func.count()).group_by(
            Combine.tier, Combine.status, Combine.outcome
        )
    ):
        bucket = combines.setdefault(
            tier, TierCombineCounts(by_status={}, by_outcome={})
        )
        bucket.by_status[status] = bucket.by_status.get(status, 0) + int(n)
        bucket.by_outcome[outcome] = bucket.by_outcome.get(outcome, 0) + int(n)

    pass_rate: dict[str, float | None] = {}
    for tier, bucket in combines.items():
        funded = bucket.by_outcome.get("passed", 0)
        failed = bucket.by_outcome.get("failed", 0)
        terminal = funded + failed
        pass_rate[tier] = round(funded / terminal, 4) if terminal else None

    pending = 0.0
    approved_unpaid = 0.0
    for state, total in db.execute(
        select(
            PayoutRequest.state,
            func.coalesce(func.sum(PayoutRequest.amount), 0.0),
        ).group_by(PayoutRequest.state)
    ):
        if state in _ACTIONABLE_PAYOUT_STATES:
            pending += float(total or 0.0)
        elif state == "approved":
            approved_unpaid += float(total or 0.0)

    now = datetime.now(timezone.utc)
    users_total = db.execute(select(func.count()).select_from(User)).scalar_one()
    users_last_30d = db.execute(
        select(func.count())
        .select_from(User)
        .where(User.created_at >= now - timedelta(days=30))
    ).scalar_one()
    tickets_open = db.execute(
        select(func.count())
        .select_from(SupportTicket)
        .where(SupportTicket.status == "open")
    ).scalar_one()

    return MetricsOut(
        mrr=round(mrr, 2),
        combines=combines,
        pass_rate=pass_rate,
        payout_liability={
            "requested_pending": round(pending, 2),
            "approved_unpaid": round(approved_unpaid, 2),
        },
        users_total=int(users_total),
        users_last_30d=int(users_last_30d),
        tickets_open=int(tickets_open),
    )


# ---------------------------------------------------------------------------
# Jobs health
# ---------------------------------------------------------------------------

# Known scheduler cadences (seconds) for the job ids registered in main.py.
# A job whose latest run started more than 3 cadences ago is flagged stale —
# the "settle_combines silently died" signal. Daily crons use 86400 (the
# Fri→Mon gap on the weekday-only chain collector sits right at the 3x edge;
# acceptable for an operator dashboard).
_JOB_CADENCE_S: dict[str, int] = {
    # Tracks config.order_monitor_interval_s (int-floored, min 1) so the
    # staleness alarm tightens/loosens with the configured cadence.
    "monitor_orders": max(1, int(settings.order_monitor_interval_s)),
    "evaluate_alerts": 30,
    "send_outbox": 30,
    "refresh_watchlist": 60,
    "prewarm_hot_tickers": 60,
    "notify_events": 60,
    "settle_combines": 300,
    "renew_combines": 86_400,
    "collect_options_chain": 86_400,
    "backup_db": 86_400,
}

_STALE_MULTIPLIER = 3


class JobHealthOut(BaseModel):
    name: str
    status: str
    duration_s: float
    error: str | None
    started_at: datetime
    cadence_s: int | None
    stale: bool


@router.get("/jobs", response_model=list[JobHealthOut])
def jobs_health(db: Session = Depends(get_session)) -> list[JobHealthOut]:
    """Latest JobRun per job name (max-id per name — ids are monotonic), with
    a staleness flag against the hardcoded cadence map above."""
    latest_ids = select(func.max(JobRun.id)).group_by(JobRun.name).scalar_subquery()
    rows = (
        db.execute(
            select(JobRun).where(JobRun.id.in_(latest_ids)).order_by(JobRun.name)
        )
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    out: list[JobHealthOut] = []
    for run in rows:
        cadence = _JOB_CADENCE_S.get(run.name)
        age_s = (now - _aware(run.started_at)).total_seconds()
        out.append(
            JobHealthOut(
                name=run.name,
                status=run.status,
                duration_s=run.duration_s,
                error=run.error,
                started_at=run.started_at,
                cadence_s=cadence,
                stale=cadence is not None and age_s > _STALE_MULTIPLIER * cadence,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class AdminActionOut(BaseModel):
    id: int
    actor_id: int
    action: str
    target_type: str
    target_id: int | None
    before: dict
    after: dict
    reason: str | None
    created_at: datetime


class AdminActionsPage(BaseModel):
    items: list[AdminActionOut]
    total: int
    page: int


def _parse_json(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


@router.get("/actions", response_model=AdminActionsPage)
def list_actions(
    target_type: str | None = None,
    target_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_session),
) -> AdminActionsPage:
    """The append-only admin audit log, newest first — how "who changed this
    account and why" gets answered."""
    stmt = select(AdminAction)
    if target_type is not None:
        stmt = stmt.where(AdminAction.target_type == target_type)
    if target_id is not None:
        stmt = stmt.where(AdminAction.target_id == target_id)
    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    rows = (
        db.execute(
            stmt.order_by(AdminAction.created_at.desc(), AdminAction.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return AdminActionsPage(
        items=[
            AdminActionOut(
                id=a.id,
                actor_id=a.actor_id,
                action=a.action,
                target_type=a.target_type,
                target_id=a.target_id,
                before=_parse_json(a.before_json),
                after=_parse_json(a.after_json),
                reason=a.reason,
                created_at=a.created_at,
            )
            for a in rows
        ],
        total=int(total),
        page=page,
    )
