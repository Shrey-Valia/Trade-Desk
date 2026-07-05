"""Scheduled combine settlement / auto-fail / auto-fund.

The combine engine (services/combine_state.combine_snapshot) settles the
5pm-PT boundary, persists a FAILED outcome on an MLL breach, auto-funds a
PASS, and writes the matching events — but lazily, only when something
reads the combine's state. That means with no traffic a combine wouldn't
fail/settle until the next read.

This job runs the engine for every non-archived combine on a clock, so
the rules fire on time regardless of reads. combine_snapshot is DB + CPU
only (realized P&L from closed trades + Black-Scholes); no network, so a
short interval is cheap. It's idempotent — settlement is gated on the
5pm-PT boundary and outcomes are terminal once set.

The same pass also runs the simulated payout REVIEW desk: a
'payout_requested' event older than PAYOUT_REVIEW_WINDOW_H auto-approves
by recording a matching 'payout_approved'. The debit happened at REQUEST
time (services/combine_state.PAYOUT_DEBIT_TYPES), so approval never moves
money — it just closes the review.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

log = logging.getLogger(__name__)

# Simulated payout review window (hours): a 'payout_requested' at least this
# old is auto-approved on the next settle pass — request → hold → approve,
# like a real payout desk. Env-overridable (PAYOUT_REVIEW_WINDOW_H).
PAYOUT_REVIEW_WINDOW_H = float(os.environ.get("PAYOUT_REVIEW_WINDOW_H", "1.0"))


def approve_pending_payouts(
    session, now: datetime | None = None, review_window_h: float | None = None
) -> int:
    """Approve 'payout_requested' events older than the review window by
    recording a 'payout_approved' with the same amount. Returns the count
    approved.

    There is no schema link between the two rows, so matching is POSITIONAL
    per combine: the N oldest requests are covered by the N existing
    approvals; anything beyond that and past the window gets approved
    (requests are paced to one per 24h, so position matching is unambiguous
    in practice). Legacy terminal 'payout' events need no approval.
    Idempotent — a re-run sees its own approvals in the counts and no-ops."""
    from models.combine_event import CombineEvent

    if now is None:
        now = datetime.now(timezone.utc)
    window_h = PAYOUT_REVIEW_WINDOW_H if review_window_h is None else review_window_h
    cutoff = now - timedelta(hours=window_h)

    requests = (
        session.execute(
            select(CombineEvent)
            .where(CombineEvent.type == "payout_requested")
            .order_by(
                CombineEvent.combine_id, CombineEvent.created_at, CombineEvent.id
            )
        )
        .scalars()
        .all()
    )
    if not requests:
        return 0
    approved_counts = dict(
        session.execute(
            select(CombineEvent.combine_id, func.count())
            .where(CombineEvent.type == "payout_approved")
            .group_by(CombineEvent.combine_id)
        ).all()
    )
    approved = 0
    position: dict[int, int] = {}
    for req in requests:
        idx = position.get(req.combine_id, 0)
        position[req.combine_id] = idx + 1
        if idx < approved_counts.get(req.combine_id, 0):
            continue  # already approved (oldest-first position match)
        if req.created_at > cutoff:
            continue  # still under review
        amount = float(req.amount or 0.0)
        session.add(
            CombineEvent(
                user_id=req.user_id,
                combine_id=req.combine_id,
                type="payout_approved",
                message=f"Payout approved — ${amount:,.2f}.",
                amount=req.amount,
            )
        )
        approved += 1
    if approved:
        session.commit()
    return approved


def settle_combines(session_factory=None) -> dict:
    """Run combine_snapshot for each active combine. Returns a small
    summary (processed count) for logging/tests. `session_factory` is
    injectable for tests; defaults to the app's SessionLocal."""
    from models.combine import Combine
    from services.combine_state import combine_snapshot

    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    session = session_factory()
    processed = 0
    failed = 0
    try:
        combines = (
            session.execute(select(Combine).where(Combine.status != "archived"))
            .scalars()
            .all()
        )
        for c in combines:
            try:
                combine_snapshot(session, c)
                processed += 1
            except Exception:  # noqa: BLE001
                failed += 1
                log.exception("settle_combines: combine %s failed", c.id)
        # Payout review desk — same 5-min clock; a failure here must not
        # mask the settle summary.
        approved = 0
        try:
            approved = approve_pending_payouts(session)
        except Exception:  # noqa: BLE001
            log.exception("settle_combines: payout approval pass failed")
        log.info(
            "settle_combines: processed=%d failed=%d of %d active combines, "
            "payouts_approved=%d",
            processed,
            failed,
            len(combines),
            approved,
        )
        return {
            "processed": processed,
            "failed": failed,
            "total": len(combines),
            "payouts_approved": approved,
        }
    finally:
        session.close()
