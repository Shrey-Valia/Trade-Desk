"""User accounts — the multi-user prop-firm shell.

Each user owns up to 5 combines (paid evaluation accounts); the one in
`active_combine_id` drives the trading terminal header and is the
combine new trades bind to.

`active_combine_id` is a plain Integer rather than a ForeignKey:
users↔combines would be circular, and SQLite cannot ALTER TABLE ADD
CONSTRAINT, so the usual use_alter escape hatch doesn't exist. Every
read path validates ownership through the combines table instead.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Stored lowercased + stripped; unique doubles as the login index.
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_combine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Copy trading: the combine whose trades are mirrored to this user's
    # follower combines (those with combine.copy_follow=True). None = copy
    # trading off. Plain Integer for the same circular-FK reason as above.
    copy_lead_combine_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
