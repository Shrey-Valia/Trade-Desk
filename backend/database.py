import logging
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event, inspect, text
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


def _assert_durable_sqlite_path(url: str) -> None:
    """Refuse to boot a production deployment on a RELATIVE sqlite path.

    `sqlite:///./data/x.db` is correct for local dev (cwd is `backend/`),
    and catastrophic in a container: resolved against the image's
    /app/backend WORKDIR it lands the database in the container's writable
    layer instead of the mounted /app/data volume. Nothing errors — the app
    comes up, serves traffic, takes signups, and loses every row the next
    time the container is recreated. Worse, the backup job writes to its
    own absolute default on the volume, so you keep BACKUPS of a database
    that isn't there.

    Absolute is the only safe form under a container (note the four
    slashes): sqlite:////app/data/dashboard.db. This mirrors the existing
    pre-tier legacy-DB refusal — a loud stop beats silent data loss.
    """
    if not settings.is_production or not url.startswith("sqlite:///"):
        return
    path = url.replace("sqlite:///", "", 1)
    if path.startswith("/"):
        return
    raise RuntimeError(
        "DATABASE_URL is a RELATIVE sqlite path "
        f"({url!r}) while APP_ENV=production. Under a container this "
        "resolves against the WORKDIR, not the mounted data volume, and "
        "the database is destroyed on every container recreate. Use an "
        "absolute path — sqlite:////app/data/dashboard.db (four slashes) "
        "— or unset DATABASE_URL to take the image default. See "
        "docs/DEPLOYMENT.md."
    )


_assert_durable_sqlite_path(settings.database_url)

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


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    """Reliability PRAGMAs for the single-file SQLite deploy.

    The app runs several concurrent writers against one file — the 20s order
    monitor, the settlement / renewal jobs, the watchlist refresh, and request
    handlers. In SQLite's default rollback-journal mode a writer blocks all
    readers, and past the driver's short default wait a losing connection
    raises `database is locked`. WAL lets readers run concurrently with a
    writer; `busy_timeout` makes a blocked writer WAIT (up to 5s) instead of
    erroring; `synchronous=NORMAL` is the WAL-safe durability setting. No-op on
    Postgres (guarded by dialect) and on in-memory test engines (which build
    their own engine without this hook). `foreign_keys` is intentionally left
    OFF here — enabling FK enforcement is a behavior change that needs its own
    test pass, not a silent flip on a live DB.
    """
    if engine.dialect.name != "sqlite":
        return
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
    finally:
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    # Import models so SQLAlchemy registers them before create_all.
    from models import (  # noqa: F401
        account_state,
        admin_action,
        agreement,
        alert,
        auth_session,
        combine,
        combine_event,
        historical_earnings_event,
        invite,
        job_run,
        kyc,
        notification,
        options_snapshot,
        password_reset,
        payment,
        payout_method,
        payout_request,
        platform_state,
        support_ticket,
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
    _additive_migrate_email_outbox()
    _migrate_money_columns()
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
    # Premium-denominated TP/SL (Tastytrade "manage winners"): multiples of
    # |net entry premium| the monitor exits at (see models/trade.py for the
    # net-debit vs net-credit semantics). Nullable — unset for legacy rows.
    ("tp_premium_mult", "FLOAT"),
    ("sl_premium_mult", "FLOAT"),
    # Resting close-limit on an open position: signed net premium per 1×
    # structure (debit positive / credit negative); monitor closes when the
    # live net mark reaches it. Nullable — unset for legacy rows.
    ("close_limit_price", "FLOAT"),
    # OCO grouping: one fill/close cancels still-working siblings in the group.
    ("oco_group", "VARCHAR(36)"),
    ("close_reason", "VARCHAR(16)"),
    # Copy trading: the lead trade a mirrored row was copied from.
    ("copied_from_trade_id", "INTEGER"),
    # Time-in-force for working orders. 'gtc' (default) preserves legacy
    # rest-indefinitely behavior; 'day' expires unfilled at the next session.
    ("time_in_force", "VARCHAR(8) NOT NULL DEFAULT 'gtc'"),
    # Accounting provenance (see models/trade.py). Legacy rows backfill to
    # 'execution' so they keep their combine-accounting weight; only the
    # manual journal-entry path stamps 'manual' (record-keeping, excluded
    # from combine equity). Additive — never triggers the tier-wipe branch.
    ("origin", "VARCHAR(12) NOT NULL DEFAULT 'execution'"),
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
        # Legacy $10K-paper-account rows pre-date the tier model and would
        # otherwise pollute the 50K combine's history — the one-time tier
        # adoption wipes them.
        #
        # DANGER: the wipe branch fires whenever `tier` is absent — which ALSO
        # happens if someone points the app at a RESTORED PRE-TIER BACKUP. That
        # is almost never a genuine legacy adoption, so a populated table now
        # REFUSES TO BOOT (before any ALTER runs — the DB is left byte-for-byte
        # untouched) unless the explicit escape hatch is set. The refusal is
        # checked FIRST so a mistaken restore is a loud, recoverable error
        # instead of a silent, irreversible history wipe.
        count = 0
        if needs_wipe:
            count = conn.execute(text("SELECT COUNT(*) FROM trades")).scalar() or 0
            if count and not settings.allow_legacy_trade_wipe:
                raise RuntimeError(
                    "REFUSING TO BOOT: the 'trades' table is missing the 'tier' "
                    f"column but contains {count} row(s). This almost certainly "
                    "means DATABASE_URL points at a RESTORED PRE-TIER BACKUP — "
                    "the legacy tier migration would irreversibly DELETE every "
                    "trade row. Nothing has been modified. To recover: stop the "
                    "app and point DATABASE_URL back at a current (post-tier) "
                    "database, or restore a newer backup from "
                    f"{settings.backup_dir!r}. If this truly is a one-time "
                    "adoption of a pre-tier legacy database and its trade "
                    "history is expendable, set ALLOW_LEGACY_TRADE_WIPE=1 for a "
                    "single boot to proceed with the wipe, then unset it."
                )
        for name, ddl in pending:
            conn.execute(text(f"ALTER TABLE trades ADD COLUMN {name} {ddl}"))
        if needs_wipe:
            if count:
                logging.getLogger(__name__).warning(
                    "MIGRATION: 'tier' column absent and "
                    "ALLOW_LEGACY_TRADE_WIPE=1 — treating this as a pre-tier "
                    "database and DELETING all %d existing trade row(s).",
                    count,
                )
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
    # Funded-stage accounting epoch (stamped at activation): from it the
    # balance restarts at the tier start, payouts debit it, and the HWM
    # basis re-seeds. Backfilled from funded_activated_at below.
    ("funded_epoch_at", "DATETIME"),
    # Copy trading: does this combine mirror the user's lead combine's trades,
    # and the size multiplier applied before clamping to its cap.
    ("copy_follow", "BOOLEAN NOT NULL DEFAULT 0"),
    ("copy_multiplier", "FLOAT NOT NULL DEFAULT 1.0"),
    # Per-follower bracket overrides (underlying price levels). NULL = inherit
    # the lead trade's stop_loss / take_profit on a mirrored open.
    ("copy_stop_loss", "FLOAT"),
    ("copy_take_profit", "FLOAT"),
    # Personal profit-target day-protect lock stamp ("protect the green day").
    # NULL = not locked; a stamp within the current 5pm-PT trading day
    # day-locks the combine until the boundary.
    ("profit_locked_at", "DATETIME"),
    # Billing period ("Billed monthly, cancel anytime"): the end of the paid
    # 30-day period (backfilled to now + 30 days for non-archived rows below)
    # and the cancel-at-period-end flag the renewal job archives on.
    ("paid_through", "DATETIME"),
    ("cancel_at_period_end", "BOOLEAN NOT NULL DEFAULT 0"),
]

# Copy trading added a lead pointer to users; per-tier DLL overrides added the
# JSON column; the DLL-off toggle added a per-tier disable list. Same
# idempotent additive pattern.
# Outbox retry scheduling (added with the real SMTP transport). Nullable
# with no default: existing rows read NULL = "eligible now", which preserves
# the previous behaviour for anything already queued.
_EMAIL_OUTBOX_COLUMN_ADDITIONS: list[tuple[str, str]] = [
    ("next_attempt_at", "DATETIME"),
]


_USER_COLUMN_ADDITIONS: list[tuple[str, str]] = [
    ("copy_lead_combine_id", "INTEGER"),
    ("dll_overrides_json", "TEXT NOT NULL DEFAULT '{}'"),
    # Per-tier DLL DISABLE flags (JSON list of tier keys). [] = DLL on.
    ("dll_disabled_json", "TEXT NOT NULL DEFAULT '[]'"),
    # Personal daily profit target as JSON {"amount", "lock"}; 'null' = unset.
    ("profit_target_json", "TEXT NOT NULL DEFAULT 'null'"),
    # Free reset credits banked by monthly rebills (jobs/renew_combines).
    ("reset_credits", "INTEGER NOT NULL DEFAULT 0"),
    # Operator back office: privilege tier + suspension stamp.
    ("role", "VARCHAR(12) NOT NULL DEFAULT 'trader'"),
    ("suspended_at", "DATETIME"),
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


def _additive_migrate_email_outbox() -> None:
    inspector = inspect(engine)
    if "email_outbox" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("email_outbox")}
    pending = [
        (name, ddl)
        for name, ddl in _EMAIL_OUTBOX_COLUMN_ADDITIONS
        if name not in existing
    ]
    if not pending:
        return
    with engine.connect() as conn:
        for name, ddl in pending:
            conn.execute(
                text(f"ALTER TABLE email_outbox ADD COLUMN {name} {ddl}")
            )
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
        # Adopt already-activated funded accounts into the funded-stage
        # accounting epoch, and re-seed their HWM basis to the tier start:
        # the epoch basis restarts the balance at the starting balance, so
        # keeping the eval-era HWM would park the MLL at/above the fresh
        # balance — an instant fail on the first read after upgrading.
        if "funded_epoch_at" in {name for name, _ in pending}:
            from services.account_tiers import TIERS

            conn.execute(
                text(
                    "UPDATE combines SET funded_epoch_at = funded_activated_at "
                    "WHERE funded_activated_at IS NOT NULL"
                )
            )
            tier_case = " ".join(
                f"WHEN '{key}' THEN {tier.starting_balance}"
                for key, tier in TIERS.items()
            )
            conn.execute(
                text(
                    f"UPDATE combines SET "
                    f"hwm = CASE tier {tier_case} ELSE hwm END, "
                    f"settled_hwm = CASE tier {tier_case} ELSE settled_hwm END "
                    f"WHERE funded_activated_at IS NOT NULL"
                )
            )
        # Give existing non-archived combines a full billing period from the
        # migration instant so nobody is instantly past-due on upgrade. Bound
        # as a naive-UTC ISO string (the UTCDateTime storage format) so the
        # sqlite3 driver needs no datetime adapter.
        if "paid_through" in {name for name, _ in pending}:
            from services.pricing import BILLING_PERIOD_DAYS

            seeded = (
                (datetime.now(timezone.utc) + timedelta(days=BILLING_PERIOD_DAYS))
                .replace(tzinfo=None)
                .isoformat(sep=" ")
            )
            conn.execute(
                text(
                    "UPDATE combines SET paid_through = :pt "
                    "WHERE status != 'archived'"
                ),
                {"pt": seeded},
            )
        conn.commit()


# Money columns migrated from FLOAT → NUMERIC(12,2) (services/money.py). A
# fresh DB gets the right type straight from create_all (the column uses the
# `Money` TypeDecorator whose impl is NUMERIC(12,2)); this ALTER only matters
# for an EXISTING Postgres DB whose columns were created as double precision.
# (table, column) pairs to widen.
_MONEY_COLUMNS: list[tuple[str, str]] = [
    ("trades", "realized_pnl"),
    ("trades", "net_debit_credit"),
    ("combines", "hwm"),
    ("combines", "settled_hwm"),
    ("payments", "amount"),
    ("combine_events", "amount"),
]


def _migrate_money_columns() -> None:
    """Widen the money columns to NUMERIC(12,2) on an existing Postgres DB.

    Guarded to NON-SQLite: SQLite has no static column types (NUMERIC affinity
    stores whatever is bound, and the `Money` type already binds an exact
    Decimal), so an ALTER … TYPE there is both unnecessary and unsupported for
    this shape — it's a no-op. On Postgres the cast is explicit and idempotent:
    we only ALTER a column whose data type isn't already `numeric`, so re-running
    on every boot does nothing once migrated. A fresh Postgres DB (the CI leg)
    never enters the loop because create_all already made the columns numeric.
    """
    if engine.dialect.name == "sqlite":
        return
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.connect() as conn:
        for table, column in _MONEY_COLUMNS:
            if table not in table_names:
                continue
            cols = {c["name"]: c for c in inspector.get_columns(table)}
            col = cols.get(column)
            if col is None:
                continue
            type_name = str(col["type"]).lower()
            if "numeric" in type_name or "decimal" in type_name:
                continue  # already migrated
            # USING casts the existing float values into the new type so no data
            # is lost; rounding to scale 2 is exactly the cent-quantization we
            # want for the historical rows.
            conn.execute(
                text(
                    f"ALTER TABLE {table} "
                    f"ALTER COLUMN {column} TYPE NUMERIC(12, 2) "
                    f"USING ROUND({column}::numeric, 2)"
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
        # exit_date drives the 5pm-PT trading-day windows (DLL, daily RPL,
        # per-day buckets) in combine_state — all filter/sort closed trades by
        # exit_date, so this backs the hottest read path.
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_trades_exit_date ON trades(exit_date)")
        )
        # Composite (user_id, status): list_combines filters by user_id and the
        # slot-cap / active-set logic filters on status — the leading column
        # also serves user_id-only lookups. The Combine model already declares
        # this index (ix_combines_user_status), so create_all builds it on a
        # FRESH DB; we re-assert it here with the SAME name (a no-op there) so a
        # LEGACY adopted DB whose table predates the model index also gets it —
        # the same belt-and-suspenders the trades indexes above use for columns
        # added by ALTER TABLE.
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_combines_user_status "
                "ON combines(user_id, status)"
            )
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
