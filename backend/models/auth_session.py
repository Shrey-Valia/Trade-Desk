"""Server-side auth sessions.

The browser cookie carries the RAW token; only its sha256 hexdigest is
stored here, so a database leak doesn't yield live sessions. Rows are
revocable (signout deletes them) and expired rows are lazily deleted on
auth lookup — no cleanup cron needed at this scale.

Named AuthSession (table auth_sessions) to stay out of SQLAlchemy
`Session`'s mental namespace.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("ix_auth_sessions_user", "user_id"),
        Index("ix_auth_sessions_expires", "expires_at"),
    )

    # sha256 hexdigest of the cookie token — 64 hex chars.
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
