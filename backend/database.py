from collections.abc import Generator
from datetime import timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool
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


def _make_engine(url: str):
    """Build the engine with backend-appropriate connection handling.

    SQLite keeps its single-file `check_same_thread=False` shim (the
    FastAPI request thread differs from the one that opened the
    connection). Everything else (Postgres in deployment / CI) gets a
    real `QueuePool`: a bounded pool with overflow headroom and
    `pool_pre_ping` so a connection killed by the server (idle timeout,
    failover) is detected and recycled instead of handed out dead. All
    knobs are env-overridable via `settings` so a small box and a big
    box can both be tuned without code changes.
    """
    if "sqlite" in url:
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            future=True,
        )
    return create_engine(
        url,
        poolclass=QueuePool,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle_s,
        future=True,
    )


engine = _make_engine(settings.database_url)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    # Import models so SQLAlchemy registers them before create_all.
    from models import (  # noqa: F401
        account_state,
        auth_session,
        combine,
        combine_event,
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
    _additive_migrate_combines()
    _additive_migrate_users()
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
    # Limit/stop orders + SL/TP brackets. order_type defaults to 'market'
    # so existing rows read as immediate fills; the rest are nullable.
    # (order_type was originally VARCHAR(8); SQLite ignores the length so the
    # widening to fit 'stop_limit' needs no ALTER — only the model metadata.)
    ("order_type", "VARCHAR(16) NOT NULL DEFAULT 'market'"),
    ("limit_price", "FLOAT"),
    # stop_limit ENTRY: arms at stop_price, then rests as a limit at limit_price.
    ("stop_price", "FLOAT"),
    # Trailing stop (EXIT): trails the favorable option mark by trail_amount
    # ($/share) or trail_pct; trail_hwm is the monitor-maintained high-water.
    ("trail_amount", "FLOAT"),
    ("trail_pct", "FLOAT"),
    ("trail_hwm", "FLOAT"),
    ("stop_loss", "FLOAT"),
    ("take_profit", "FLOAT"),
    # OCO grouping: one fill/close cancels still-working siblings in the group.
    ("oco_group", "VARCHAR(36)"),
    ("close_reason", "VARCHAR(16)"),
    # Copy trading: the lead trade a mirrored row was copied from.
    ("copied_from_trade_id", "INTEGER"),
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


# Combine settlement engine added a settled HWM, a settlement timestamp,
# and a permanent pass/fail outcome to `combines`. Same idempotent
# additive pattern. settled_hwm is backfilled to each row's running hwm
# so the migration is behaviour-preserving at the instant it runs (the
# MLL floor doesn't jump), then stays fixed intraday going forward.
_COMBINE_COLUMN_ADDITIONS: list[tuple[str, str]] = [
    ("settled_hwm", "FLOAT NOT NULL DEFAULT 0"),
    ("last_settled_at", "DATETIME"),
    ("outcome", "VARCHAR(16) NOT NULL DEFAULT 'active'"),
    # Funded-account lifecycle: when the eval passed (NULL = not funded) and
    # the eval-restart point set by a reset (NULL = original eval).
    ("funded_at", "DATETIME"),
    ("eval_reset_at", "DATETIME"),
    # Real (simulated) pricing: the path + split chosen at purchase, and
    # when the funded account was activated. Defaults match a legacy combine
    # bought on the standard 80/20 activation path; funded_activated_at is
    # backfilled from funded_at below so existing funded accounts stay
    # unlocked rather than suddenly requiring an activation payment.
    ("pricing_path", "VARCHAR(16) NOT NULL DEFAULT 'activation'"),
    ("profit_split", "FLOAT NOT NULL DEFAULT 0.8"),
    ("funded_activated_at", "DATETIME"),
    # Copy trading: does this combine mirror the user's lead combine's trades,
    # and the size multiplier applied before clamping to its cap.
    ("copy_follow", "BOOLEAN NOT NULL DEFAULT 0"),
    ("copy_multiplier", "FLOAT NOT NULL DEFAULT 1.0"),
]

# Copy trading added a lead pointer to users; per-tier DLL overrides added the
# JSON column. Same idempotent additive pattern.
_USER_COLUMN_ADDITIONS: list[tuple[str, str]] = [
    ("copy_lead_combine_id", "INTEGER"),
    ("dll_overrides_json", "TEXT NOT NULL DEFAULT '{}'"),
]


def _additive_migrate_users() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("users")}
    pending = [
        (name, ddl) for name, ddl in _USER_COLUMN_ADDITIONS if name not in existing
    ]
    if not pending:
        return
    with engine.connect() as conn:
        for name, ddl in pending:
            conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
        conn.commit()


def _additive_migrate_combines() -> None:
    inspector = inspect(engine)
    if "combines" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("combines")}
    pending = [
        (name, ddl) for name, ddl in _COMBINE_COLUMN_ADDITIONS if name not in existing
    ]
    if not pending:
        return
    with engine.connect() as conn:
        for name, ddl in pending:
            conn.execute(text(f"ALTER TABLE combines ADD COLUMN {name} {ddl}"))
        # Seed settled_hwm to the existing running hwm so the floor is
        # unchanged at migration time (DEFAULT 0 would crater it).
        if "settled_hwm" in {name for name, _ in pending}:
            conn.execute(text("UPDATE combines SET settled_hwm = hwm"))
        # Treat already-funded legacy accounts as activated so they keep
        # their payout access (the activation gate only applies to combines
        # funded after this column exists).
        if "funded_activated_at" in {name for name, _ in pending}:
            conn.execute(
                text(
                    "UPDATE combines SET funded_activated_at = funded_at "
                    "WHERE funded_at IS NOT NULL"
                )
            )
        conn.commit()


def _create_missing_indexes() -> None:
    """Indexes the additive column list can't express. Idempotent via
    IF NOT EXISTS."""
    with engine.connect() as conn:
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_trades_combine_id ON trades(combine_id)")
        )
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_trades_oco_group ON trades(oco_group)")
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
            # Never derive a login from a committed default — mint a random
            # password when none is configured (the dev user is a migration
            # artifact; set DEV_USER_PASSWORD to log in as it).
            import secrets

            password = settings.dev_user_password or secrets.token_urlsafe(24)
            dev_user = User(
                email=settings.dev_user_email,
                password_hash=hash_password(password),
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
                settled_hwm=max(legacy_hwm, tier.starting_balance),
                status="active",
                outcome="active",
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
