"""Scheduled subscription renewal — makes "Billed monthly, cancel anytime"
true in the simulation.

Each combine carries paid_through (seeded to purchase + 30 days by
provision_combine, backfilled for legacy rows by the boot migration). Once
that boundary passes, this daily job either:

  * ARCHIVES the combine when cancel_at_period_end is set — mirroring the
    archive endpoint's exact field semantics (status flip + repointing the
    owner's active combine to the newest survivor), with a 'sub_ended'
    event; or
  * AUTO-RENEWS: one simulated Payment at the combine's monthly price per
    30-day period (status 'paid', the same ledger row a purchase writes),
    paid_through extended FROM ITS OLD VALUE (a multi-period gap bills each
    period), and ONE free reset credit banked per period (Topstep parity —
    every rebill banks a reset), capped at pricing.RESET_CREDIT_CAP.

Idempotent per boundary: extending paid_through past `now` IS the marker
that a period was billed, so a re-run is a no-op. Simulated economics —
no real money moves, but the ledger reads like the real thing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

log = logging.getLogger(__name__)


def _archive_at_period_end(session, combine) -> None:
    """Mirror POST /combines/{id}/archive semantics (routers/combines.py):
    status flip + repoint the owner's active combine to the newest remaining
    non-archived one — written on the models so a job doesn't call a router."""
    from models.combine import Combine
    from models.user import User
    from services.combine_state import record_event

    combine.status = "archived"
    user = session.get(User, combine.user_id)
    if user is not None and user.active_combine_id == combine.id:
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
    record_event(
        session, combine, "sub_ended", "Subscription ended — combine archived."
    )
    session.add(combine)


def _renew(session, combine, now: datetime) -> int:
    """Bill every completed 30-day period since paid_through: one Payment +
    one event + one banked reset credit (capped) per period. Returns the
    number of periods billed."""
    from models.payment import Payment
    from models.user import User
    from services.combine_state import record_event
    from services.pricing import BILLING_PERIOD_DAYS, RESET_CREDIT_CAP, monthly_price

    price = monthly_price(combine.tier, combine.pricing_path, combine.profit_split)
    owner = session.get(User, combine.user_id)
    periods = 0
    while combine.paid_through <= now:
        combine.paid_through = combine.paid_through + timedelta(
            days=BILLING_PERIOD_DAYS
        )
        periods += 1
        session.add(
            Payment(
                user_id=combine.user_id,
                combine_id=combine.id,
                tier=combine.tier,
                amount=price,
                status="paid",
            )
        )
        banked = False
        if owner is not None and int(owner.reset_credits or 0) < RESET_CREDIT_CAP:
            owner.reset_credits = int(owner.reset_credits or 0) + 1
            banked = True
        record_event(
            session,
            combine,
            "renewal",
            f"Subscription renewed — ${price:,.0f} billed."
            + (" Free reset credit banked." if banked else ""),
            amount=price,
        )
    if owner is not None:
        session.add(owner)
    session.add(combine)
    return periods


def renew_combines(session_factory=None, now: datetime | None = None) -> dict:
    """Run the billing boundary for every non-archived combine. Returns a
    small summary for logging/tests. `session_factory` is injectable for
    tests; defaults to the app's SessionLocal. `now` is injectable so tests
    can pin the boundary instant."""
    from models.combine import Combine
    from services.pricing import BILLING_PERIOD_DAYS

    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    if now is None:
        now = datetime.now(timezone.utc)
    session = session_factory()
    renewed = archived = periods = seeded = failed = 0
    try:
        combines = (
            session.execute(select(Combine).where(Combine.status != "archived"))
            .scalars()
            .all()
        )
        for combine in combines:
            try:
                if combine.paid_through is None:
                    # Legacy row that predates the billing columns and missed
                    # the boot backfill — seed a fresh period, bill nothing.
                    combine.paid_through = now + timedelta(days=BILLING_PERIOD_DAYS)
                    session.add(combine)
                    seeded += 1
                elif combine.paid_through > now:
                    continue
                elif combine.cancel_at_period_end:
                    _archive_at_period_end(session, combine)
                    archived += 1
                else:
                    periods += _renew(session, combine, now)
                    renewed += 1
                session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
                failed += 1
                log.exception("renew_combines: combine %s failed", combine.id)
        summary = {
            "renewed": renewed,
            "archived": archived,
            "periods": periods,
            "seeded": seeded,
            "failed": failed,
            "total": len(combines),
        }
        log.info("renew_combines: %s", summary)
        return summary
    finally:
        session.close()
