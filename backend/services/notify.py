"""Notification fan-out: in-app rows + the transactional-email outbox.

`notify` is the one call sites use for "tell this user something
happened": it inserts the in-app Notification (header bell) and, unless
email=False, queues the matching EmailOutbox row. Neither function SENDS
anything — jobs/send_outbox.py drains the queue through the mailer — so
request paths stay fast and every send is retryable + auditable.

Transaction convention: like services.combine_state.record_event, these
add rows to the caller's session and DO NOT COMMIT — the caller lands the
notification atomically with whatever state change caused it (a payout
denial that commits without its notification, or vice versa, would lie).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.notification import EmailOutbox, Notification
from models.user import User


def enqueue_email(
    db: Session,
    to_email: str,
    template: str,
    subject: str,
    body: str,
    user_id: int | None = None,
) -> EmailOutbox:
    """Queue one outbound email (no in-app row) — for mail that isn't a
    user lifecycle notification (password resets, ops alerts). Does NOT
    commit; the caller owns the transaction."""
    row = EmailOutbox(
        user_id=user_id,
        to_email=to_email,
        template=template,
        # Defensive truncation to the column widths — SQLite doesn't enforce
        # VARCHAR lengths but Postgres would reject the row.
        subject=subject[:160],
        body=body,
        status="queued",
    )
    db.add(row)
    return row


def notify(
    db: Session,
    user: User,
    kind: str,
    title: str,
    body: str,
    email: bool = True,
) -> Notification:
    """Insert an in-app notification for `user` and (when email=True) queue
    the matching email to their address. Does NOT commit; the caller owns
    the transaction."""
    row = Notification(
        user_id=user.id,
        kind=kind,
        title=title[:120],
        body=body[:500],
    )
    db.add(row)
    if email:
        enqueue_email(
            db,
            to_email=user.email,
            template=kind,
            subject=title,
            body=body,
            user_id=user.id,
        )
    return row
