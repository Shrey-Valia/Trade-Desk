"""Lifecycle-event notifier — tails combine_events into notifications.

Scheduled every 60s in main.py (wrapped in run_logged). Reads the last
processed combine_events.id from the platform_state KV (key
"notify_events_watermark") and fans out email + in-app notifications for
every newer event whose type is in the map below.

First run on an existing database SEEDS the watermark at the current max
event id and notifies nothing — adopting the notifier must never replay
months of history into a user's inbox.

Event-type map (the actual strings written via combine_state.record_event
— see services/combine_state.py, routers/combines.py, jobs/renew_combines.py,
jobs/settle_combines.py, services/order_monitor.py):

  emailed:   funded, failed, payout_requested, payout_approved,
             payout_denied (future — payout desk), reset, renewal,
             sub_ended, activation, liquidated
  in-app only: personal_dll, profit_target (day-lock alerts — can fire
             daily; the bell is the right volume, email would be spam)
  skipped:   settled (daily per-combine noise), sub_cancel / sub_resume
             (user-initiated clicks with immediate UI feedback), legacy
             "payout" (historical terminal type), anything unknown.

Transaction discipline: the batch's notification/outbox rows and the
advanced watermark land in ONE commit (platform_state.set_value commits
the session) — a crash mid-batch re-processes the same events next run
instead of ever skipping any.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import func, select

log = logging.getLogger(__name__)

WATERMARK_KEY = "notify_events_watermark"

# Max events processed per run; the watermark advances only to the last
# PROCESSED id, so a bigger backlog just takes extra runs.
BATCH_SIZE = 200

# Commit-grace lag (seconds). The id watermark assumes commit order == id
# order — true on SQLite (single writer, the default deploy) but NOT on
# Postgres: a transaction can INSERT event id N, then commit AFTER a
# shorter transaction that inserted id N+1 already committed and was
# notified — advancing the watermark past N, which then commits invisibly
# and is skipped forever (a lost payout email). Guard: never process an
# event younger than this grace, and never advance the watermark past one.
# Every combine_event write happens inside a short request/job transaction
# (well under this window), so a 30s grace makes the out-of-order case
# effectively impossible while only delaying a notification by up to the
# grace on top of the 60s job cadence (fine for lifecycle email).
COMMIT_GRACE_S = 30


def _amount_suffix(ev) -> str:
    return f" — ${float(ev.amount):,.2f}" if ev.amount is not None else ""


# type → (title builder, send email too?). Bodies reuse the event's own
# human-written message (it already carries the dollar amounts / reasons).
_EVENT_MAP: dict[str, tuple[Callable, bool]] = {
    "funded": (lambda ev: "Your combine passed — account funded", True),
    "failed": (lambda ev: "Combine failed", True),
    "payout_requested": (lambda ev: f"Payout requested{_amount_suffix(ev)}", True),
    "payout_approved": (lambda ev: f"Payout approved{_amount_suffix(ev)}", True),
    "payout_denied": (lambda ev: f"Payout denied{_amount_suffix(ev)}", True),
    "reset": (lambda ev: "Combine reset — fresh evaluation started", True),
    "renewal": (lambda ev: f"Subscription renewed{_amount_suffix(ev)}", True),
    "sub_ended": (lambda ev: "Subscription ended — combine archived", True),
    "activation": (lambda ev: "Funded account activated", True),
    "liquidated": (lambda ev: "Positions auto-liquidated", True),
    "personal_dll": (lambda ev: "Personal daily loss limit hit", False),
    "profit_target": (lambda ev: "Profit target reached", False),
}


def notify_events(session_factory=None, now: datetime | None = None) -> dict:
    """Process combine_events past the watermark. Returns {"notified": n}.
    `session_factory` and `now` are injectable for tests; defaults to
    SessionLocal / current UTC."""
    from models.combine_event import CombineEvent
    from models.user import User
    from services import platform_state
    from services.notify import notify

    if session_factory is None:
        from database import SessionLocal

        session_factory = SessionLocal
    if now is None:
        now = datetime.now(timezone.utc)
    safe_cutoff = now - timedelta(seconds=COMMIT_GRACE_S)
    session = session_factory()
    try:
        watermark = platform_state.get_value(session, WATERMARK_KEY)
        if watermark is None:
            # First run: seed at the current head — never replay history.
            max_id = session.execute(
                select(func.max(CombineEvent.id))
            ).scalar() or 0
            platform_state.set_value(session, WATERMARK_KEY, int(max_id))  # commits
            log.info("notify_events: watermark seeded at %d", max_id)
            return {"notified": 0}

        events = (
            session.execute(
                select(CombineEvent)
                .where(CombineEvent.id > int(watermark))
                .order_by(CombineEvent.id)
                .limit(BATCH_SIZE)
            )
            .scalars()
            .all()
        )
        if not events:
            return {"notified": 0}

        notified = 0
        users: dict[int, User | None] = {}
        last_id = int(watermark)
        for ev in events:
            # STOP at the first event younger than the commit grace — do NOT
            # process it and do NOT advance the watermark past it. A
            # lower-id event may still be mid-commit (Postgres out-of-order);
            # leaving the watermark below this id lets a later pass pick both
            # up in id order once they've aged past the grace. created_at is
            # tz-aware (UTCDateTime); guard a naive value defensively.
            created = ev.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created > safe_cutoff:
                break
            last_id = ev.id
            spec = _EVENT_MAP.get(ev.type)
            if spec is None:
                continue  # unmapped/unknown type — advance past it silently
            if ev.user_id not in users:
                users[ev.user_id] = session.get(User, ev.user_id)
            user = users[ev.user_id]
            if user is None:
                continue
            title_fn, email = spec
            notify(
                session,
                user,
                kind=ev.type,
                title=title_fn(ev),
                body=ev.message,
                email=email,
            )
            notified += 1

        # One commit for the batch + watermark (set_value commits).
        platform_state.set_value(session, WATERMARK_KEY, last_id)
        if notified:
            log.info(
                "notify_events: notified=%d (watermark -> %d)", notified, last_id
            )
        return {"notified": notified}
    finally:
        session.close()
