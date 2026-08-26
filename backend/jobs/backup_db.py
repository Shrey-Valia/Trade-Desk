"""Nightly SQLite backup with retention (P0 wave 2026-07, workstream B4).

Uses sqlite3's ONLINE BACKUP API (`sqlite3.Connection.backup`), which is
safe to run against a live database that other connections are actively
writing: the backup engine copies pages under SQLite's own locking
protocol and automatically restarts the copy if the source changes
mid-flight, so the destination file is always a transactionally
consistent snapshot — WAL content included. The app's concurrent writers
(the 20s order monitor, settlement/renewal jobs, request handlers) are
never blocked and never corrupted. This is NOT true of naively copying
the .db file with shutil/cp, which can capture a torn page mid-write.

Behavior:
- Non-SQLite engine (Postgres deployment) → no-op, returns
  ``{"status": "skipped"}``. Use pg_dump / managed snapshots there.
- SQLite → writes ``dashboard-YYYYMMDD-HHMMSS.db`` (UTC stamp) into
  ``settings.backup_dir`` (created if missing), then prunes backup files
  older than ``settings.backup_retention_days`` and prunes old JobRun
  rows via ``services.job_runs.prune_job_runs``.
- Then, when ``backup_offsite_provider`` is set, mirrors the snapshot to
  object storage and applies remote retention (``services.offsite_backup``).
  OFF by default. This matters because ``backup_dir`` sits on the SAME
  volume as the live database, so a local backup does not survive losing
  that volume; an offsite failure fails the job — see
  ``_replicate_offsite``.

Scheduled daily at 02:30 ET in main.py via ``run_logged("backup_db", …)``
— off trading hours and clear of the 00:15 ET billing run.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from config import settings

log = logging.getLogger(__name__)

# Only files this job itself wrote are retention-pruned — a hand-made
# copy someone drops in the directory is never deleted.
_BACKUP_GLOB = "dashboard-*.db"


def backup_db_if_stale(max_age_h: float = 20.0) -> dict:
    """Boot catch-up: run backup_db() only when the newest existing backup is
    older than max_age_h (or none exists). Mirrors the renew_combines startup
    catch-up — the 02:30 ET cron lives in an in-memory jobstore, so a host
    that is down at that instant (a dev box, a market-hours-only server)
    otherwise NEVER backs up and, since prune_job_runs only runs inside
    backup_db, its JobRun table grows unbounded. Cheap and safe to call on
    every startup: a no-op when a recent backup already exists.

    Non-SQLite engines: delegates to backup_db (which skips), so the JobRun
    prune it also performs still runs.

    NOTE the asymmetry with the 02:30 cron: this swallows every exception to
    protect startup, so a boot-time OFFSITE failure lands in the log (and
    Sentry, via the logging integration) but leaves the `backup_db` JobRun row
    GREEN until the next cron run turns it red. Right after configuring a
    bucket, confirm it with `scripts/offsite_backup_check.py put` rather than
    reading the jobs view."""
    try:
        from database import engine as app_engine

        if app_engine.dialect.name != "sqlite":
            return backup_db()  # non-sqlite: skips backup, still prunes JobRuns

        dest_dir = Path(settings.backup_dir)
        newest = 0.0
        if dest_dir.is_dir():
            for candidate in dest_dir.glob(_BACKUP_GLOB):
                try:
                    newest = max(newest, candidate.stat().st_mtime)
                except OSError:
                    continue
        if newest and (time.time() - newest) < max_age_h * 3600:
            log.info(
                "backup_db_if_stale: a backup <%.0fh old exists — skipping",
                max_age_h,
            )
            return {"status": "skipped", "reason": "recent backup exists"}
        return backup_db()
    except Exception:  # noqa: BLE001 — a catch-up must never break startup
        log.exception("backup_db_if_stale failed")
        return {"status": "error"}


def backup_db(
    engine=None,
    backup_dir: str | None = None,
    retention_days: int | None = None,
) -> dict:
    """Snapshot the live SQLite DB, prune old backups + JobRun rows.

    All parameters default to the app's live engine/settings so the
    scheduler can call this with no arguments; tests pass their own
    tmp-file engine and directory.
    """
    if engine is None:
        from database import engine as app_engine

        engine = app_engine

    if engine.dialect.name != "sqlite":
        log.info(
            "backup_db: engine dialect is %r, not sqlite — skipping "
            "(use pg_dump / managed snapshots for Postgres)",
            engine.dialect.name,
        )
        return {"status": "skipped", "reason": f"non-sqlite engine ({engine.dialect.name})"}

    dest_dir = Path(backup_dir if backup_dir is not None else settings.backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"dashboard-{stamp}.db"

    # A pooled DBAPI connection to the LIVE database. In SQLAlchemy 2.x
    # raw_connection() returns a PoolProxiedConnection; .driver_connection
    # is the actual sqlite3.Connection the backup API needs
    # (.dbapi_connection is the pre-2.0 spelling, kept as a fallback).
    raw = engine.raw_connection()
    try:
        src = getattr(raw, "driver_connection", None) or raw.dbapi_connection
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        raw.close()

    days = retention_days if retention_days is not None else settings.backup_retention_days
    cutoff = time.time() - days * 86_400
    pruned_backups = 0
    for candidate in dest_dir.glob(_BACKUP_GLOB):
        if candidate == dest:
            continue
        try:
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink()
                pruned_backups += 1
        except OSError:  # raced with a manual cleanup — not worth failing the job
            log.warning("backup_db: could not prune %s", candidate, exc_info=True)

    from services.job_runs import prune_job_runs

    pruned_job_runs = prune_job_runs()

    log.info(
        "backup_db: wrote %s (pruned %d old backup(s), %d job-run row(s))",
        dest,
        pruned_backups,
        pruned_job_runs,
    )
    result = {
        "status": "ok",
        "file": str(dest),
        "pruned_backups": pruned_backups,
        "pruned_job_runs": pruned_job_runs,
    }
    # Offsite copy LAST, so a flaky object store can never stop the local
    # snapshot or either prune from happening.
    result.update(_replicate_offsite(dest))
    return result


def _replicate_offsite(dest: Path) -> dict:
    """Mirror `dest` to object storage when a provider is configured, then
    apply remote retention. Returns a summary to merge into the job result;
    `{"offsite": "disabled"}` when replication is off (the default).

    Failures RAISE, deliberately. By this point the local snapshot exists
    and both prunes have run, so the only thing left to report is that the
    copy which survives losing this volume did not happen — and a green
    `backup_db` row next to an empty bucket is the exact silent failure
    offsite replication exists to prevent. The message leads with the local
    outcome so an operator reading a red row in Admin → Jobs is not misled
    into thinking there is no backup at all.
    """
    from services.offsite_backup import OffsiteBackupError, get_offsite_store, prune_remote

    try:
        store = get_offsite_store()
        if store is None:
            return {"offsite": "disabled"}
        put = store.put_file(dest, dest.name)
        pruned = prune_remote(
            store, retention_days=settings.backup_offsite_retention_days
        )
    except Exception as exc:
        raise OffsiteBackupError(
            f"LOCAL snapshot {dest.name} OK; OFFSITE copy FAILED — {exc}"
        ) from exc
    return {
        "offsite": "ok",
        "offsite_key": put["key"],
        "offsite_bytes": put["bytes"],
        "pruned_offsite": pruned,
    }
