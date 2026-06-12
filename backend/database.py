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
        account_state,
        auth_session,
        combine,
        historical_earnings_event,
        options_snapshot,
        payment,
        ticker_selection,
        trade,
        user,
        user_star,
        watchlist_item,
    )

    Base.metadata.create_all(bind=engine)
    _additive_migrate_trades()
    _create_missing_indexes()
    # AccountState seeding retired with the multi-user shell — the table
    # stays on disk purely as the migration source for legacy HWMs.
    _backfill_multiuser(SessionLocal)


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
    # Combine-tier introduction — trades opened before tiers existed
    # were on the legacy $10K paper account. We wipe those legacy rows
    # immediately after adding the column (see _wipe_legacy_trades).
    ("tier", "VARCHAR(8) NOT NULL DEFAULT '50K'"),
    # Multi-user shell — which combine instance owns this trade.
    # Backfilled from `tier` by _backfill_multiuser().
    ("combine_id", "INTEGER"),
]


def _additive_migrate_trades() -> None:
    inspector = inspect(engine)
    if "trades" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("trades")}
    pending = [
        (name, ddl) for name, ddl in _TRADE_COLUMN_ADDITIONS if name not in existing
    ]
    needs_wipe = "tier" in {name for name, _ in pending}
    if not pending:
        return
    with engine.connect() as conn:
        for name, ddl in pending:
            conn.execute(text(f"ALTER TABLE trades ADD COLUMN {name} {ddl}"))
        # Legacy $10K-paper-account rows pre-date the tier model and
        # would otherwise pollute the 50K combine's history. Wipe them.
        if needs_wipe:
            conn.execute(text("DELETE FROM trades"))
        conn.commit()


def _create_missing_indexes() -> None:
    """Indexes the additive column list can't express. Idempotent via
    IF NOT EXISTS."""
    with engine.connect() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_trades_combine_id ON trades(combine_id)")
        )
        conn.commit()


def _backfill_multiuser(session_factory: sessionmaker) -> None:
    """One-time adoption of a pre-multi-user database.

    The guard is the idempotency key AND the fresh-install short-circuit:
    if no trade rows have a NULL combine_id there is nothing to adopt —
    a brand-new DB therefore gets NO dev user (signup-first flow).

    For a legacy DB: create the dev user (settings creds), one combine
    per distinct tier among unmapped trades (HWM carried from the old
    AccountState per-tier columns), a 'migration_grant' payment per
    combine, map the trades, and point active_combine_id at the combine
    matching the legacy active_tier.

    Takes the session factory as a parameter so tests can run it
    against their own engine.
    """
    from sqlalchemy import select

    from models.account_state import AccountState
    from models.combine import Combine
    from models.payment import Payment
    from models.trade import Trade
    from models.user import User
    from services.account_tiers import DEFAULT_TIER, TIERS
    from services.auth import hash_password
    from services.combine_objectives import generate_account_code

    with session_factory() as session:
        unmapped_tiers = session.execute(
            select(Trade.tier).where(Trade.combine_id.is_(None)).distinct()
        ).scalars().all()
        if not unmapped_tiers:
            return

        legacy = session.get(AccountState, 1)
        legacy_active_tier = legacy.active_tier if legacy else DEFAULT_TIER

        dev_user = session.execute(
            select(User).where(User.email == settings.dev_user_email)
        ).scalar_one_or_none()
        if dev_user is None:
            dev_user = User(
                email=settings.dev_user_email,
                password_hash=hash_password(settings.dev_user_password),
                display_name="Dev",
            )
            session.add(dev_user)
            session.flush()

        active_combine_id: int | None = None
        first_combine_id: int | None = None
        for tier_key in sorted(unmapped_tiers):
            tier = TIERS.get(tier_key)
            if tier is None:
                # Unknown tier string in legacy data — leave those rows
                # unmapped rather than guessing an account size.
                continue
            legacy_hwm = legacy.get_hwm(tier_key) if legacy else tier.starting_balance
            combine = Combine(
                user_id=dev_user.id,
                tier=tier_key,
                name=f"{tier_key} Combine",
                account_code=generate_account_code(session, tier_key, dev_user.id),
                hwm=max(legacy_hwm, tier.starting_balance),
                status="active",
            )
            session.add(combine)
            session.flush()
            session.add(
                Payment(
                    user_id=dev_user.id,
                    combine_id=combine.id,
                    tier=tier_key,
                    amount=None,
                    status="migration_grant",
                )
            )
            session.execute(
                text(
                    "UPDATE trades SET combine_id = :cid "
                    "WHERE tier = :tier AND combine_id IS NULL"
                ),
                {"cid": combine.id, "tier": tier_key},
            )
            if first_combine_id is None:
                first_combine_id = combine.id
            if tier_key == legacy_active_tier:
                active_combine_id = combine.id

        if dev_user.active_combine_id is None:
            dev_user.active_combine_id = active_combine_id or first_combine_id
        session.commit()


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
