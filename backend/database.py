from collections.abc import Generator
from datetime import timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from config import settings


class UTCDateTime(TypeDecorator):
    """Always store as UTC, always read back as tz-aware UTC.

    SQLite has no native timezone storage, so `DateTime(timezone=True)`
    silently drops tzinfo on the round-trip. This TypeDecorator makes
    the storage layer transparently UTC-aware regardless of backend.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            # Treat naive as already-UTC; better than crashing on bind.
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


# SQLite needs the directory to exist before the file is opened.
if settings.database_url.startswith("sqlite:///"):
    db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    # Import models so SQLAlchemy registers them before create_all.
    from models import (  # noqa: F401
        historical_earnings_event,
        options_snapshot,
        trade,
        watchlist_item,
    )

    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
