"""Admin-action audit log — append-only, written by EVERY admin mutation.

The moment manual balance adjustments, refunds, suspensions, and payout
decisions exist, "who changed this account and why" must be answerable —
for disputed bans, internal fraud, and chargeback evidence. Rows are never
mutated or deleted.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class AdminAction(Base):
    __tablename__ = "admin_actions"
    __table_args__ = (
        Index("ix_admin_actions_actor", "actor_id"),
        Index("ix_admin_actions_target", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The admin who acted.
    actor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # Verb slug, e.g. "user.suspend", "payout.deny", "payment.refund",
    # "combine.adjust", "platform.set_mode".
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    # What it acted on: "user" | "combine" | "payment" | "payout_request"
    # | "support_ticket" | "platform".
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Before/after snapshots of the fields the action changed, as JSON.
    before_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    after_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
