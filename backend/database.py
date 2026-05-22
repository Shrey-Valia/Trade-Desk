from collections.abc import Generator
from datetime import timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine, inspect, text
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
    _additive_migrate_trades()


# Single-user SQLite — Alembic would be overkill, but we DO need to
# add Phase-2 nullable columns to existing `trades` rows without
# dropping data. This helper inspects the live schema and runs only
# the ALTER TABLE statements that haven't been applied yet. Idempotent
# on every boot; safe to call on a fresh DB (table exists with full
# schema → all columns already present → no-op).
_TRADE_COLUMN_ADDITIONS: list[tuple[str, str]] = [
    ("tags_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("mistake_tags_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("confidence", "INTEGER"),
    ("thesis", "TEXT"),
    ("planned_exit", "TEXT"),
    ("risk_amount", "FLOAT"),
    ("screenshot_url", "TEXT"),
    ("review_note", "TEXT"),
]


def _additive_migrate_trades() -> None:
    inspector = inspect(engine)
    if "trades" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("trades")}
    pending = [
        (name, ddl) for name, ddl in _TRADE_COLUMN_ADDITIONS if name not in existing
    ]
    if not pending:
        return
    with engine.connect() as conn:
        for name, ddl in pending:
            conn.execute(text(f"ALTER TABLE trades ADD COLUMN {name} {ddl}"))
        conn.commit()


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
