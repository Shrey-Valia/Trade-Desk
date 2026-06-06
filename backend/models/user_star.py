"""User-starred tickers — favorites surfaced in the search modal.

The product runs single-tenant locally, so `user_id` defaults to 1
across the codebase. Carrying it as a column anyway means that
when multi-user lands, we add an auth layer and a real users table
without a schema migration.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Index, Integer, String, UniqueConstraint
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
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
