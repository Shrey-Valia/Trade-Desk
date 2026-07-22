"""Server-side price-alert evaluation.

Before this job, price alerts were only evaluated by the FRONTEND's 15s
poll — close the tab and every alert went blind (the audit's finding).
This pass runs on the scheduler: it sweeps ALL users' active price alerts,
trips them against one batched quote fetch, and lands each trip in the
in-app notification bell + email outbox so the alert works with no tab open.

The pure crossing rule is shared with the interactive endpoint
(routers.alerts.price_alert_tripped) so client, endpoint and job can never
disagree about what "tripped" means. Idempotent: a tripped alert flips to
status='triggered' and won't re-fire until the user re-arms it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

log = logging.getLogger(__name__)


def evaluate_alerts(session_factory=None, *, quotes_for=None) -> dict:
    """One evaluation pass. Returns {evaluated, triggered} for logging/tests.
    `quotes_for(symbols) -> {symbol: quote}` is injectable for tests."""
    from sqlalchemy import select

    from models.alert import Alert
    from models.user import User
    from routers.alerts import price_alert_tripped
    from services.notify import notify

    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    if quotes_for is None:
        from services.alpaca_client import get_quotes

        quotes_for = get_quotes

    session = session_factory()
    try:
        active = (
            session.execute(
                select(Alert)
                .where(Alert.status == "active")
                .where(Alert.kind == "price")
            )
            .scalars()
            .all()
        )
        if not active:
            return {"evaluated": 0, "triggered": 0}

        symbols = sorted({a.symbol for a in active})
        try:
            quotes = quotes_for(symbols)
        except Exception:  # noqa: BLE001 — feed cold → alerts stay active
            log.debug("evaluate_alerts: quote fetch failed for %s", symbols)
            return {"evaluated": len(active), "triggered": 0}

        now = datetime.now(UTC)
        triggered = 0
        for alert in active:
            quote = quotes.get(alert.symbol)
            # A missing or non-positive price is NOT a real cross (a zero
            # price would trip every "below" alert permanently).
            if quote is None or not (quote.price > 0):
                continue
            if not price_alert_tripped(alert.direction, alert.threshold, quote.price):
                continue
            alert.status = "triggered"
            alert.triggered_at = now
            owner = session.get(User, alert.user_id)
            if owner is not None:
                arrow = "≥" if alert.direction == "above" else "≤"
                notify(
                    session,
                    owner,
                    kind="price_alert",
                    title=f"{alert.symbol} {arrow} {alert.threshold:g} — price alert hit",
                    body=(
                        f"{alert.symbol} traded {quote.price:.2f}, crossing your "
                        f"{alert.direction} {alert.threshold:g} alert."
                        + (f" Note: {alert.note}" if alert.note else "")
                    ),
                )
            triggered += 1
        if triggered:
            session.commit()
        return {"evaluated": len(active), "triggered": triggered}
    finally:
        session.close()
