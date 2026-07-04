"""User-starred tickers — favorites surfaced in the search modal.

Multi-user: every star belongs to a real account (user_id → users.id) and
every insert path must pass user_id explicitly. There is deliberately NO
column default — a call site that forgets user_id fails loudly at flush
instead of silently filing the star under someone else's account.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class UserStar(Base):
    __tablename__ = "user_stars"
    __table_args__ = (
        # One star per (user, symbol). Doubles as a lookup index for
        # GET /api/user/stars which filters by user_id.
        UniqueConstraint("user_id", "symbol", name="uq_user_stars_user_symbol"),
        Index("ix_user_stars_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The FK applies to fresh installs only — SQLite can't retrofit a
    # constraint onto an existing table without a rebuild — but the ORM
    # contract (explicit user_id, no default) holds everywhere.
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
