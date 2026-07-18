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

The same pass also runs the payout desk's AUTO-APPROVE fallback
(services/payout_desk.auto_approve_pass): a payout_requests row still in
state 'requested' after the review window approves unattended when
settings.payout_auto_approve is on. Rows an operator pulled into review
(under_review / held) are never auto-approved. The debit happened at
REQUEST time (services/combine_state.PAYOUT_DEBIT_TYPES), so approval
never moves money — it just closes the review.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from sqlalchemy import select

from config import settings

log = logging.getLogger(__name__)

# Payout review window (hours) — how old a still-'requested' payout must be
# before the auto-approve fallback closes it. Owned by
# settings.payout_review_window_h; the legacy PAYOUT_REVIEW_WINDOW_H env var
# (and this module attribute, which tests monkeypatch) still win here for
# backward compatibility.
PAYOUT_REVIEW_WINDOW_H = float(
    os.environ.get("PAYOUT_REVIEW_WINDOW_H", str(settings.payout_review_window_h))
)


def approve_pending_payouts(
    session, now: datetime | None = None, review_window_h: float | None = None
) -> int:
    """Auto-approve payout requests past the review window. Kept under its
    legacy name for the job's call sites; the real logic now lives in
    services/payout_desk.auto_approve_pass, operating ONLY on payout_requests
    workflow rows — legacy event-pair history (pre-PayoutRequest bookkeeping)
    is left untouched. Returns the count approved (0 when
    settings.payout_auto_approve is off)."""
    from services.payout_desk import auto_approve_pass

    window_h = PAYOUT_REVIEW_WINDOW_H if review_window_h is None else review_window_h
    return auto_approve_pass(session, now=now, review_window_h=window_h)


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
