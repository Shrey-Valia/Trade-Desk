"""Email-outbox drain — sends queued EmailOutbox rows through the mailer.

Scheduled every 30s in main.py (wrapped in run_logged). Oldest-first, at
most BATCH_SIZE rows per run so one enormous backlog can't pin the
scheduler thread. Per-row error isolation: a failing send increments
attempts + records last_error and the row stays 'queued' for the next
run, flipping to 'failed' (terminal) once attempts reach
settings.mail_max_attempts. Success stamps status='sent' + sent_at.

One commit per run lands the whole batch's status updates; a crash
mid-run re-sends at most this batch (console mail is idempotent; SMTP
duplicates are the standard at-least-once trade-off for an outbox).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from config import settings

log = logging.getLogger(__name__)

# Max rows drained per run. At the 30s cadence this is ~100 mails/min of
# steady-state throughput — far beyond what the platform generates.
BATCH_SIZE = 50


def send_outbox(session_factory=None) -> dict:
    """Drain the queued outbox. Returns {"sent": n, "failed": n} — `failed`
    counts rows that hit the terminal attempt cap THIS run (a transient
    failure that will retry is neither). `session_factory` is injectable
    for tests; defaults to the app's SessionLocal."""
    from models.notification import EmailOutbox
    from services.mailer import get_mailer

    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    session = session_factory()
    sent = 0
    failed = 0
    try:
        rows = (
            session.execute(
                select(EmailOutbox)
                .where(EmailOutbox.status == "queued")
                .order_by(EmailOutbox.id)
                .limit(BATCH_SIZE)
            )
            .scalars()
            .all()
        )
        if not rows:
            return {"sent": 0, "failed": 0}
        mailer = get_mailer()
        for row in rows:
            try:
                mailer.send(row.to_email, row.subject, row.body)
            except Exception as exc:  # noqa: BLE001 — per-row isolation
                row.attempts += 1
                row.last_error = repr(exc)[:300]
                if row.attempts >= settings.mail_max_attempts:
                    row.status = "failed"
                    failed += 1
                    log.error(
                        "send_outbox: mail %s to=%s failed permanently "
                        "after %d attempts: %s",
                        row.id,
                        row.to_email,
                        row.attempts,
                        row.last_error,
                    )
                else:
                    log.warning(
                        "send_outbox: mail %s to=%s failed (attempt %d/%d): %s",
                        row.id,
                        row.to_email,
                        row.attempts,
                        settings.mail_max_attempts,
                        row.last_error,
                    )
            else:
                row.status = "sent"
                row.sent_at = datetime.now(timezone.utc)
                sent += 1
        session.commit()
        if sent or failed:
            log.info("send_outbox: sent=%d failed=%d", sent, failed)
        return {"sent": sent, "failed": failed}
    finally:
        session.close()
