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
"""

from __future__ import annotations

import logging

from sqlalchemy import select

log = logging.getLogger(__name__)


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
        log.info(
            "settle_combines: processed=%d failed=%d of %d active combines",
            processed,
            failed,
            len(combines),
        )
        return {"processed": processed, "failed": failed, "total": len(combines)}
    finally:
        session.close()
