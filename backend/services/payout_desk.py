"""Payout adjudication desk — the human review engine over payout_requests.

The MONEY ledger stays in combine_events: 'payout_requested' DEBITS the
funded balance at request time (funds are held while review runs) and
'payout_denied' RE-CREDITS the same amount (services/combine_state nets
the two). This module owns the WORKFLOW state machine on top of that
ledger — models/payout_request.PayoutRequest:

    requested / under_review / held → approve | deny | hold
    held → resume_review (→ under_review)
    approved → mark_paid
    denied, paid — terminal

Money discipline (the invariants tests pin):
  * request  → the ONLY debit (booked by the endpoint at request time)
  * deny     → the ONLY credit (the 'payout_denied' event written here)
  * approve / hold / resume_review / mark_paid → move NOTHING; approve and
    deny just stamp decided_at + reviewer_id and echo the ledger event.

Transactions: `create_request` does NOT commit (the payout endpoint owns
that transaction — the event and the workflow row land atomically);
`decide` and `auto_approve_pass` COMMIT themselves, since their callers
(the C2 admin router, the settle job) treat each decision as a unit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from config import settings
from models.combine import Combine
from models.payout_request import PayoutRequest
from models.user import User
from services.combine_state import record_event

# Denial reason taxonomy (industry prop-firm TOS language). The CODE is the
# stable machine key stored on the row + routed on by the frontend; the label
# is what the trader sees. "other" requires the reviewer note to say why.
DENIAL_REASONS: dict[str, str] = {
    "rule_breach": "Trading rule breach",
    "prohibited_strategy": "Prohibited trading strategy",
    "news_window_abuse": "Trading around restricted news windows",
    "correlated_trading": "Correlated or coordinated trading across accounts",
    "sim_exploit": "Exploiting simulation or execution artifacts",
    "verification_incomplete": "Identity or tax verification incomplete",
    "chargeback_risk": "Payment dispute / chargeback risk",
    "other": "Other (see reviewer note)",
}

# System-voided reasons — stamped by lifecycle transitions (reset, refund),
# never selectable by a reviewer, hence NOT in DENIAL_REASONS.
SYSTEM_REASONS: dict[str, str] = {
    "account_reset": "Voided — the account was reset",
}

# Every code → trader-facing label (the GET payout-requests / admin queue
# lookup — covers both reviewer denials and system voids).
REASON_LABELS: dict[str, str] = {**DENIAL_REASONS, **SYSTEM_REASONS}

DECISION_ACTIONS = ("approve", "deny", "hold", "resume_review", "mark_paid")

# States a reviewer may still decide (approve/deny/hold) from.
_DECIDABLE_STATES = ("requested", "under_review", "held")

# Non-terminal states a lifecycle void (reset / refund) sweeps up.
_VOIDABLE_STATES = ("requested", "under_review", "held")


def _cas_state(
    db: Session, request_id: int, new_state: str, allowed_states: tuple[str, ...]
) -> bool:
    """Compare-and-swap the workflow state — the concurrency guard.

    A conditional UPDATE ... WHERE state IN (allowed) claims the transition
    atomically on BOTH SQLite (single-writer serialization) and Postgres
    (row-level lock on the UPDATE): of two overlapping decisions, exactly one
    matches the WHERE and wins; the loser's rowcount is 0. Ledger events are
    written only AFTER a won claim, so a double-deny can never book two
    re-credits and the auto-approve pass can never overwrite a concurrent
    deny (same race class request_payout guards with SELECT ... FOR UPDATE).
    """
    result = db.execute(
        update(PayoutRequest)
        .where(
            PayoutRequest.id == request_id,
            PayoutRequest.state.in_(allowed_states),
        )
        .values(state=new_state)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0) == 1


def _debit_in_current_epoch(db: Session, req: PayoutRequest) -> bool:
    """Whether the request's original DEBIT still counts in the combine's
    current funded-epoch window (the `since` filter payouts_booked and the
    router mirrors apply). False when the epoch was cleared (reset) or
    re-stamped after the request — the debit is already out of scope, so a
    denial must NOT book a re-credit against the NEW epoch's ledger."""
    combine = db.get(Combine, req.combine_id)
    epoch = getattr(combine, "funded_epoch_at", None) if combine else None
    if epoch is None:
        return False
    requested_at = req.requested_at
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=timezone.utc)
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=timezone.utc)
    return requested_at >= epoch


def create_request(
    db: Session, user: User, combine: Combine, amount: float
) -> PayoutRequest:
    """Book a payout request: the 'payout_requested' ledger event (the debit)
    AND the workflow row, in the caller's open transaction — one commit lands
    both or neither, so the ledger and the review queue can never disagree.
    The row's amount is exactly the event's amount. Does NOT commit."""
    amount = float(amount)
    record_event(
        db,
        combine,
        "payout_requested",
        f"Payout requested — ${amount:,.2f} (pending review).",
        amount=amount,
    )
    row = PayoutRequest(
        user_id=user.id,
        combine_id=combine.id,
        amount=amount,
        state="requested",
    )
    db.add(row)
    db.flush()  # assign the id so callers can reference the row immediately
    return row


def _invalid_transition(action: str, state: str) -> HTTPException:
    return HTTPException(
        409,
        f"invalid_transition: cannot {action} a payout request in state "
        f"'{state}'",
    )


def decide(
    db: Session,
    request_id: int,
    action: str,
    reviewer_id: int | None,
    reason_code: str | None = None,
    note: str | None = None,
    commit: bool = True,
) -> PayoutRequest:
    """Apply one reviewer action to a payout request (strict state machine —
    see module docstring). Commits (unless ``commit=False``). Returns the
    updated row.

    Pass ``commit=False`` when the caller needs the decision and its audit row
    to land in ONE transaction: committing here first would leave a window where
    a crash lands the payout decision — the most money-sensitive admin action —
    with no audit trail (the admin router stages the audit row and commits).

    approve → 'payout_approved' event (same amount; bookkeeping only — the
    debit stayed booked from request time). deny → 'payout_denied' event
    (same amount; THE ledger re-credit) + reason_code/note stored. hold
    parks the row; resume_review un-parks it; mark_paid closes an approved
    request (disbursement stays simulated — no money moves here either).
    """
    if action not in DECISION_ACTIONS:
        raise HTTPException(
            422,
            "unknown_action: action must be one of " + ", ".join(DECISION_ACTIONS),
        )
    req = db.get(PayoutRequest, request_id)
    if req is None:
        raise HTTPException(
            404, f"payout_request_not_found: payout request {request_id} not found"
        )
    # Validation that must NOT consume the transition happens before the CAS.
    if action == "deny" and reason_code not in DENIAL_REASONS:
        raise HTTPException(
            422,
            "unknown_reason_code: reason_code must be one of "
            + ", ".join(sorted(DENIAL_REASONS)),
        )
    now = datetime.now(timezone.utc)
    amount = float(req.amount or 0.0)

    _TARGETS: dict[str, tuple[str, tuple[str, ...]]] = {
        "approve": ("approved", _DECIDABLE_STATES),
        "deny": ("denied", _DECIDABLE_STATES),
        "hold": ("held", _DECIDABLE_STATES),
        "resume_review": ("under_review", ("held",)),
        "mark_paid": ("paid", ("approved",)),
    }
    new_state, allowed = _TARGETS[action]

    # Claim the transition atomically; on a lost race, surface the ACTUAL
    # current state in the 409 (rollback first — the failed UPDATE is still
    # part of this transaction).
    if not _cas_state(db, request_id, new_state, allowed):
        db.rollback()
        db.refresh(req)
        raise _invalid_transition(action, req.state)
    # The identity-map row predates the CAS — sync it before the metadata
    # writes below (refresh re-reads inside the open transaction, so the
    # claimed state is visible and stays ours until commit).
    db.refresh(req)

    if action == "approve":
        combine = db.get(Combine, req.combine_id)
        req.reviewer_id = reviewer_id
        req.decided_at = now
        if note is not None:
            req.note = note
        record_event(
            db,
            combine,
            "payout_approved",
            f"Payout approved — ${amount:,.2f}.",
            amount=amount,
        )
    elif action == "deny":
        combine = db.get(Combine, req.combine_id)
        req.reason_code = reason_code
        req.note = note
        req.reviewer_id = reviewer_id
        req.decided_at = now
        if _debit_in_current_epoch(db, req):
            # This event IS the ledger re-credit: combine_state nets it
            # against the request-time debit, returning the held funds.
            record_event(
                db,
                combine,
                "payout_denied",
                f"Payout denied — ${amount:,.2f} returned to the account. "
                f"Reason: {DENIAL_REASONS[reason_code]}."[:160],
                amount=amount,
            )
        else:
            # STALE EPOCH: the original debit predates the current funded
            # epoch (a reset/re-activation happened since the request), so
            # the epoch filter already forgot it — booking a re-credit here
            # would offset the NEW epoch's genuine debits (a double-payout
            # hole). Record the denial for history/notification with NO
            # ledger amount (payouts_booked sums NULL amounts as zero).
            req.note = ((note + " — ") if note else "") + (
                "stale epoch: no ledger re-credit (original debit predates "
                "the current funded epoch)"
            )
            record_event(
                db,
                combine,
                "payout_denied",
                f"Payout denied — ${amount:,.2f} (prior account stint). "
                f"Reason: {DENIAL_REASONS[reason_code]}."[:160],
                amount=None,
            )
    elif action == "hold":
        if note is not None:
            req.note = note
    # resume_review / mark_paid: the CAS state change is the whole action.

    db.add(req)
    if commit:
        db.commit()
        db.refresh(req)
    else:
        db.flush()
    return req


def void_requests(
    db: Session,
    combine_id: int,
    reason_code: str,
    include_approved: bool = False,
) -> int:
    """Lifecycle void: sweep a combine's live payout requests into the
    terminal 'cancelled' state with NO ledger event. Used by reset (the
    epoch reset already discards the debit — a re-credit would double it)
    and refund/chargeback archival (the account is dead; a charged-back
    account gets no re-credit and no later mark_paid). Does NOT commit —
    runs inside the caller's transaction. Returns the count voided."""
    if reason_code not in SYSTEM_REASONS and reason_code not in DENIAL_REASONS:
        raise ValueError(f"unknown void reason_code {reason_code!r}")
    states = _VOIDABLE_STATES + (("approved",) if include_approved else ())
    result = db.execute(
        update(PayoutRequest)
        .where(
            PayoutRequest.combine_id == combine_id,
            PayoutRequest.state.in_(states),
        )
        .values(
            state="cancelled",
            reason_code=reason_code,
            decided_at=datetime.now(timezone.utc),
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def auto_approve_pass(
    db: Session,
    now: datetime | None = None,
    review_window_h: float | None = None,
) -> int:
    """The settle-job hook: when settings.payout_auto_approve is on, approve
    (reviewer_id=None — "system") every request still in state 'requested'
    that is at least the review window old. Rows an operator has touched
    (under_review / held) are NEVER auto-approved — pulling a request into
    review pins it until a human decides. Commits; returns the count.

    Legacy pre-PayoutRequest history (bare event pairs) is untouched: this
    pass reads ONLY the payout_requests workflow table."""
    if not settings.payout_auto_approve:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)
    window_h = (
        settings.payout_review_window_h if review_window_h is None else review_window_h
    )
    cutoff = now - timedelta(hours=window_h)
    rows = (
        db.execute(
            select(PayoutRequest)
            .join(Combine, Combine.id == PayoutRequest.combine_id)
            .where(
                PayoutRequest.state == "requested",
                PayoutRequest.requested_at <= cutoff,
                # Lifecycle guard: an archived (refunded/charged-back) or
                # FAILED combine must never be auto-paid — those requests
                # wait for a human in the admin queue (or a lifecycle void).
                Combine.status != "archived",
                Combine.outcome != "failed",
            )
            .order_by(PayoutRequest.requested_at, PayoutRequest.id)
        )
        .scalars()
        .all()
    )
    approved = 0
    for req in rows:
        # Per-row CAS: an admin decision (deny/hold) landing between our
        # SELECT and this claim wins — the conditional UPDATE misses and the
        # row is skipped instead of silently overwritten back to approved.
        if not _cas_state(db, req.id, "approved", ("requested",)):
            continue
        db.refresh(req)
        combine = db.get(Combine, req.combine_id)
        amount = float(req.amount or 0.0)
        req.reviewer_id = None  # the auto-approve fallback, not a human
        req.decided_at = now
        record_event(
            db,
            combine,
            "payout_approved",
            f"Payout approved — ${amount:,.2f}.",
            amount=amount,
        )
        db.add(req)
        approved += 1
    if approved or rows:
        db.commit()
    return approved
