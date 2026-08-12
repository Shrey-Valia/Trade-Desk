"""Invite codes — the gate on account creation for a closed launch.

One row per invitation. A code is SINGLE-USE: redemption stamps
`redeemed_at`/`redeemed_by_id` through a conditional UPDATE, so two
concurrent signups racing the same code cannot both win.

Optionally bound to an email (`email`), in which case only that address may
redeem it, and optionally expiring (`expires_at`, NULL = never). An admin
can `revoke` an unredeemed code at any time.

**Codes are stored in plaintext, deliberately.** Auth sessions and
password-reset tokens are hashed because they *authenticate* an existing
account; an invite code only permits creating a fresh, empty one. With mail
still console-only, the operator has to read the code back out of the
console to send it by hand — a write-only column would mean a code lost on
a page refresh is a code that must be reissued. Single-use + revocable +
expiring + the signup rate limiter is the containment here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class Invite(Base):
    __tablename__ = "invites"
    __table_args__ = (
        Index("ix_invites_code", "code", unique=True),
        Index("ix_invites_email", "email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The transcribable code the invitee types at signup, e.g. "TD-7K4M-QX92".
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    # When set, ONLY this (normalized, lowercase) email may redeem the code.
    # NULL = any email — a hand-off code for someone whose address we don't
    # know yet.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Operator's note to self: who this is for, which cohort, why.
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_by_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # NULL = never expires.
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    redeemed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    redeemed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
