"""Outbound notifications: the email outbox + the in-app notification center.

`email_outbox` is the transactional-email queue: services/notify.py enqueues,
jobs/send_outbox.py drains through the provider-agnostic mailer
(services/mailer.py — console logger by default, SMTP via env). Queue-then-
send keeps request paths fast and makes every send retryable + auditable.

`notifications` is the in-app mirror (bell in the header): same lifecycle
events, persisted so a trader who was away still sees what happened
(liquidated, funded, payout status) instead of learning it from support.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        # Drain query: queued rows, oldest first.
        Index("ix_email_outbox_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # NULL for non-user mail (ops alerts).
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Template slug, e.g. "password_reset", "payout_approved".
    template: Mapped[str] = mapped_column(String(48), nullable=False)
    subject: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # "queued" | "sent" | "failed" (failed = attempts exhausted).
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # Bell query: a user's recent notifications, newest first.
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # Kind slug mirrors the combine_event type where applicable
    # ("funded", "failed", "payout_denied", …) plus non-event kinds
    # ("support_reply", "system").
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
