"""Email-outbox drain — sends queued EmailOutbox rows through the mailer.

Scheduled every 30s in main.py (wrapped in run_logged). Oldest-first, at
most BATCH_SIZE rows per run so one enormous backlog can't pin the
scheduler thread. Per-row error isolation: a failing send increments
attempts + records last_error and the row stays 'queued' for the next
run, flipping to 'failed' (terminal) once attempts reach
settings.mail_max_attempts. Success stamps status='sent' + sent_at.

RETRY SCHEDULING. Retries are spaced by _BACKOFF, not by the job cadence.
Without it the 30s cadence burned all five attempts ~2.5 minutes after the
first failure, so a brief provider outage PERMANENTLY dropped whatever was
queued — and for a password reset that is the difference between a late
email and an account nobody can get back into. The schedule below spans
about five hours instead.

PERMANENT vs TRANSIENT. A 5xx refusal (bad recipient, message rejected)
will fail identically on every retry, so it goes terminal immediately
rather than sitting in the queue for hours pretending it might land. Only
transient errors — connection refused, timeout, 4xx — get the backoff.

One commit per run lands the whole batch's status updates; a crash
mid-run re-sends at most this batch (console mail is idempotent; SMTP
duplicates are the standard at-least-once trade-off for an outbox).
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from config import settings

log = logging.getLogger(__name__)

# Delay before attempt N+1, indexed by the attempt count just recorded.
# Roughly 1m, 5m, 20m, 1h, 3h — five attempts spanning ~4.5 hours, which
# outlives an ordinary provider incident. The last entry repeats if
# mail_max_attempts is raised above len(_BACKOFF).
_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=20),
    timedelta(hours=1),
    timedelta(hours=3),
)


def _is_permanent(exc: BaseException) -> bool:
    """True for refusals that will fail the same way on every retry.

    SMTP 5xx is by definition permanent (RFC 5321): a bad mailbox or a
    rejected message. Retrying it for hours only delays the operator
    noticing. Anything else — DNS, connection refused, timeouts, 4xx — is
    treated as transient and backed off.
    """
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return True
    code = getattr(exc, "smtp_code", None)
    return isinstance(code, int) and 500 <= code < 600

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
        now = datetime.now(timezone.utc)
        rows = (
            session.execute(
                select(EmailOutbox)
                .where(
                    EmailOutbox.status == "queued",
                    # NULL = never failed yet (or predates the column), so
                    # eligible immediately.
                    or_(
                        EmailOutbox.next_attempt_at.is_(None),
                        EmailOutbox.next_attempt_at <= now,
                    ),
                )
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
                permanent = _is_permanent(exc)
                if permanent or row.attempts >= settings.mail_max_attempts:
                    row.status = "failed"
                    failed += 1
                    log.error(
                        "send_outbox: mail %s to=%s failed permanently "
                        "after %d attempts (%s): %s",
                        row.id,
                        row.to_email,
                        row.attempts,
                        "5xx refusal" if permanent else "attempts exhausted",
                        row.last_error,
                    )
                else:
                    delay = _BACKOFF[min(row.attempts - 1, len(_BACKOFF) - 1)]
                    row.next_attempt_at = now + delay
                    log.warning(
                        "send_outbox: mail %s to=%s failed (attempt %d/%d), "
                        "retrying in %s: %s",
                        row.id,
                        row.to_email,
                        row.attempts,
                        settings.mail_max_attempts,
                        delay,
                        row.last_error,
                    )
            else:
                row.status = "sent"
                row.sent_at = now
                sent += 1
        session.commit()
        if sent or failed:
            log.info("send_outbox: sent=%d failed=%d", sent, failed)
        return {"sent": sent, "failed": failed}
    finally:
        session.close()
