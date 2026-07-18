"""Email + notification pipeline (workstream B3): notify fan-out, the
outbox drain job, the combine_events lifecycle notifier, and the
/api/notifications endpoints (including cross-user scoping)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from config import settings
from jobs.notify_events import COMMIT_GRACE_S, WATERMARK_KEY, notify_events
from jobs.send_outbox import send_outbox
from models.combine_event import CombineEvent
from models.notification import EmailOutbox, Notification
from models.user import User
from services import platform_state
from services.notify import enqueue_email, notify
from tests.conftest import make_combine


# -- test doubles -------------------------------------------------------------

class RecordingMailer:
    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


class FailingMailer:
    def __init__(self, error: str = "boom"):
        self.error = error
        self.calls = 0

    def send(self, to: str, subject: str, body: str) -> None:
        self.calls += 1
        raise RuntimeError(self.error)


def _make_user(session, email: str = "notify@test.local") -> User:
    user = User(email=email, password_hash="x")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# -- services/notify ----------------------------------------------------------

def test_notify_writes_notification_and_outbox(session_factory):
    session = session_factory()
    user = _make_user(session)
    notify(session, user, "funded", "You are funded", "Nice work.")
    session.commit()

    n = session.execute(select(Notification)).scalars().all()
    assert len(n) == 1
    assert n[0].user_id == user.id
    assert n[0].kind == "funded"
    assert n[0].title == "You are funded"
    assert n[0].body == "Nice work."
    assert n[0].read_at is None

    o = session.execute(select(EmailOutbox)).scalars().all()
    assert len(o) == 1
    assert o[0].to_email == user.email
    assert o[0].user_id == user.id
    assert o[0].template == "funded"
    assert o[0].subject == "You are funded"
    assert o[0].status == "queued"
    assert o[0].attempts == 0
    session.close()


def test_notify_email_false_writes_no_outbox(session_factory):
    session = session_factory()
    user = _make_user(session)
    notify(session, user, "personal_dll", "DLL hit", "Alert only.", email=False)
    session.commit()
    assert len(session.execute(select(Notification)).scalars().all()) == 1
    assert session.execute(select(EmailOutbox)).scalars().all() == []
    session.close()


def test_enqueue_email_without_user(session_factory):
    session = session_factory()
    enqueue_email(
        session, "ops@test.local", "ops_alert", "Something", "happened"
    )
    session.commit()
    row = session.execute(select(EmailOutbox)).scalar_one()
    assert row.user_id is None
    assert row.to_email == "ops@test.local"
    assert row.status == "queued"
    session.close()


# -- jobs/send_outbox ---------------------------------------------------------

def test_send_outbox_empty_queue(session_factory):
    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 0}


def test_send_outbox_drains_oldest_first(session_factory, monkeypatch):
    session = session_factory()
    enqueue_email(session, "a@test.local", "t", "first", "b1")
    enqueue_email(session, "b@test.local", "t", "second", "b2")
    session.commit()
    session.close()

    mailer = RecordingMailer()
    monkeypatch.setattr("services.mailer.get_mailer", lambda: mailer)
    assert send_outbox(session_factory=session_factory) == {"sent": 2, "failed": 0}
    assert [s[1] for s in mailer.sent] == ["first", "second"]

    check = session_factory()
    rows = check.execute(select(EmailOutbox).order_by(EmailOutbox.id)).scalars().all()
    assert all(r.status == "sent" for r in rows)
    assert all(r.sent_at is not None for r in rows)
    check.close()

    # Nothing left queued: a re-run sends nothing more.
    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 0}
    assert len(mailer.sent) == 2


def test_send_outbox_failure_retries_then_fails_at_max(session_factory, monkeypatch):
    session = session_factory()
    enqueue_email(session, "x@test.local", "t", "doomed", "long " * 200)
    session.commit()
    session.close()

    mailer = FailingMailer(error="e" * 400)
    monkeypatch.setattr("services.mailer.get_mailer", lambda: mailer)
    monkeypatch.setattr(settings, "mail_max_attempts", 2)

    # Attempt 1: transient failure — still queued for retry, not yet 'failed'.
    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 0}
    check = session_factory()
    row = check.execute(select(EmailOutbox)).scalar_one()
    assert row.status == "queued"
    assert row.attempts == 1
    assert row.last_error is not None and len(row.last_error) <= 300
    check.close()

    # Attempt 2 == mail_max_attempts: terminal.
    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 1}
    check = session_factory()
    row = check.execute(select(EmailOutbox)).scalar_one()
    assert row.status == "failed"
    assert row.attempts == 2
    assert row.sent_at is None
    check.close()

    # Terminal rows are never re-attempted.
    assert send_outbox(session_factory=session_factory) == {"sent": 0, "failed": 0}
    assert mailer.calls == 2


# -- jobs/notify_events -------------------------------------------------------

def _trader(session) -> User:
    return session.execute(
        select(User).where(User.email == "trader@test.local")
    ).scalar_one()


def _ripe() -> datetime:
    """A `now` far enough ahead that events just written in a test have aged
    past the notifier's commit grace (COMMIT_GRACE_S) and are eligible to
    process — the grace exists to defend the Postgres out-of-order-commit
    race, not to hold back already-committed events in a test."""
    return datetime.now(timezone.utc) + timedelta(seconds=COMMIT_GRACE_S + 60)


def _add_event(
    session, user_id: int, combine_id: int, type_: str,
    message: str = "msg", amount: float | None = None,
) -> CombineEvent:
    ev = CombineEvent(
        user_id=user_id, combine_id=combine_id, type=type_,
        message=message, amount=amount,
    )
    session.add(ev)
    session.commit()
    session.refresh(ev)
    return ev


def test_notify_events_first_run_seeds_watermark_without_spamming(
    auth_client, session_factory
):
    combine = make_combine(auth_client)
    session = session_factory()
    user = _trader(session)
    # Pre-existing history that must NOT be replayed on adoption.
    ev = _add_event(session, user.id, combine["id"], "funded", "Passed long ago.")

    assert notify_events(session_factory=session_factory, now=_ripe()) == {"notified": 0}

    session.expire_all()
    assert session.execute(select(Notification)).scalars().all() == []
    assert session.execute(select(EmailOutbox)).scalars().all() == []
    assert platform_state.get_value(session, WATERMARK_KEY) == ev.id
    session.close()


def test_notify_events_new_funded_event_notifies_once_idempotent(
    auth_client, session_factory
):
    combine = make_combine(auth_client)
    session = session_factory()
    user = _trader(session)

    notify_events(session_factory=session_factory, now=_ripe())  # seed watermark
    ev = _add_event(
        session, user.id, combine["id"], "funded",
        "Evaluation passed — account funded.",
    )

    assert notify_events(session_factory=session_factory, now=_ripe()) == {"notified": 1}
    session.expire_all()
    n = session.execute(select(Notification)).scalar_one()
    assert n.user_id == user.id
    assert n.kind == "funded"
    assert n.title == "Your combine passed — account funded"
    assert n.body == "Evaluation passed — account funded."
    o = session.execute(select(EmailOutbox)).scalar_one()
    assert o.to_email == user.email
    assert o.template == "funded"
    assert o.status == "queued"

    # Idempotent: the watermark advanced, so a re-run notifies nothing new.
    assert notify_events(session_factory=session_factory, now=_ripe()) == {"notified": 0}
    session.expire_all()
    assert len(session.execute(select(Notification)).scalars().all()) == 1
    assert len(session.execute(select(EmailOutbox)).scalars().all()) == 1
    assert platform_state.get_value(session, WATERMARK_KEY) == ev.id
    session.close()


def test_notify_events_amount_lands_in_title(auth_client, session_factory):
    combine = make_combine(auth_client)
    session = session_factory()
    user = _trader(session)
    notify_events(session_factory=session_factory, now=_ripe())  # seed
    _add_event(
        session, user.id, combine["id"], "payout_requested",
        "Payout requested — $1,234.50 (pending review).", amount=1234.5,
    )
    assert notify_events(session_factory=session_factory, now=_ripe()) == {"notified": 1}
    session.expire_all()
    n = session.execute(select(Notification)).scalar_one()
    assert n.title == "Payout requested — $1,234.50"
    session.close()


def test_notify_events_skips_unknown_types_but_advances(
    auth_client, session_factory
):
    combine = make_combine(auth_client)
    session = session_factory()
    user = _trader(session)
    notify_events(session_factory=session_factory, now=_ripe())  # seed
    _add_event(session, user.id, combine["id"], "settled", "Daily settlement.")
    last = _add_event(session, user.id, combine["id"], "mystery_type", "??")

    assert notify_events(session_factory=session_factory, now=_ripe()) == {"notified": 0}
    session.expire_all()
    assert session.execute(select(Notification)).scalars().all() == []
    # Watermark still advances past skipped events — they're not reprocessed.
    assert platform_state.get_value(session, WATERMARK_KEY) == last.id
    session.close()


def test_notify_events_day_lock_alert_is_in_app_only(
    auth_client, session_factory
):
    combine = make_combine(auth_client)
    session = session_factory()
    user = _trader(session)
    notify_events(session_factory=session_factory, now=_ripe())  # seed
    _add_event(
        session, user.id, combine["id"], "personal_dll",
        "Personal daily loss limit hit — alert only.",
    )
    assert notify_events(session_factory=session_factory, now=_ripe()) == {"notified": 1}
    session.expire_all()
    assert len(session.execute(select(Notification)).scalars().all()) == 1
    assert session.execute(select(EmailOutbox)).scalars().all() == []
    session.close()


def test_notify_events_holds_events_within_commit_grace(
    auth_client, session_factory
):
    """The commit-grace guard: an event younger than COMMIT_GRACE_S is NOT
    processed and does NOT advance the watermark past it — so a lower-id
    event still mid-commit (the Postgres out-of-order race) can be picked up
    on a later pass instead of being skipped forever."""
    combine = make_combine(auth_client)
    session = session_factory()
    user = _trader(session)
    notify_events(session_factory=session_factory, now=_ripe())  # seed
    seeded_watermark = platform_state.get_value(session, WATERMARK_KEY)
    ev = _add_event(
        session, user.id, combine["id"], "funded", "Just funded.",
    )

    # Evaluate at the event's own instant — inside the grace window.
    at_creation = ev.created_at
    if at_creation.tzinfo is None:
        at_creation = at_creation.replace(tzinfo=timezone.utc)
    assert notify_events(
        session_factory=session_factory, now=at_creation
    ) == {"notified": 0}
    session.expire_all()
    # Nothing sent, and the watermark did NOT jump past the fresh event.
    assert session.execute(select(Notification)).scalars().all() == []
    assert platform_state.get_value(session, WATERMARK_KEY) == seeded_watermark

    # Once it has aged past the grace, the same event notifies normally.
    assert notify_events(
        session_factory=session_factory, now=_ripe()
    ) == {"notified": 1}
    session.expire_all()
    assert platform_state.get_value(session, WATERMARK_KEY) == ev.id
    session.close()


# -- /api/notifications -------------------------------------------------------

def test_notifications_require_auth(client):
    assert client.get("/api/notifications").status_code == 401
    assert client.post("/api/notifications/read", json={}).status_code == 401


def test_notifications_list_and_unread_count(auth_client, session_factory):
    session = session_factory()
    user = _trader(session)
    notify(session, user, "funded", "First", "b", email=False)
    notify(session, user, "failed", "Second", "b", email=False)
    session.commit()
    session.close()

    res = auth_client.get("/api/notifications")
    assert res.status_code == 200
    body = res.json()
    assert body["unread"] == 2
    assert [i["title"] for i in body["items"]] == ["Second", "First"]  # newest first
    assert all(i["read_at"] is None for i in body["items"])


def test_notifications_mark_read_specific_then_all(auth_client, session_factory):
    session = session_factory()
    user = _trader(session)
    a = notify(session, user, "funded", "A", "b", email=False)
    notify(session, user, "failed", "B", "b", email=False)
    session.commit()
    a_id = a.id
    session.close()

    res = auth_client.post("/api/notifications/read", json={"ids": [a_id]})
    assert res.status_code == 204
    body = auth_client.get("/api/notifications").json()
    assert body["unread"] == 1
    read_by_title = {i["title"]: i["read_at"] for i in body["items"]}
    assert read_by_title["A"] is not None
    assert read_by_title["B"] is None

    # No ids → mark everything read. Idempotent for already-read rows.
    assert auth_client.post("/api/notifications/read", json={}).status_code == 204
    body = auth_client.get("/api/notifications").json()
    assert body["unread"] == 0
    assert all(i["read_at"] is not None for i in body["items"])


def test_notifications_scoped_per_user(
    auth_client, second_user_client, session_factory
):
    session = session_factory()
    user_a = _trader(session)
    user_b = session.execute(
        select(User).where(User.email == "rival@test.local")
    ).scalar_one()
    notify(session, user_a, "funded", "A only", "b", email=False)
    b_row = notify(session, user_b, "funded", "B only", "b", email=False)
    session.commit()
    b_id = b_row.id
    session.close()

    # A's list never shows B's notification.
    a_body = auth_client.get("/api/notifications").json()
    assert [i["title"] for i in a_body["items"]] == ["A only"]
    assert a_body["unread"] == 1

    # A marking B's id does nothing to B.
    assert (
        auth_client.post(
            "/api/notifications/read", json={"ids": [b_id]}
        ).status_code
        == 204
    )
    b_body = second_user_client.get("/api/notifications").json()
    assert b_body["unread"] == 1
    assert b_body["items"][0]["read_at"] is None
