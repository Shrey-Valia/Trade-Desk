"""Scheduled-job observability: wrap every APScheduler job in a run record.

`run_logged(name, fn)` returns a callable that executes `fn` and writes a
JobRun row (status/duration/error) in its OWN session, best-effort — a
failure to record must never break the job, and a failing job must still
re-raise so APScheduler's own error logging keeps working. The admin
jobs-health endpoint reads the latest row per name; a job whose latest row
is stale or 'error' is the "settle_combines silently died" signal that
previously only existed in untailed logs.

Row growth is bounded by `prune_job_runs` (called from the nightly backup
job): monitor_orders at 20s cadence writes ~4.3k rows/day, so a 14-day
window keeps the table around 60k rows — trivial for SQLite, but not
unbounded.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _record(name: str, status: str, duration_s: float, error: str | None) -> None:
    """Write one JobRun row, best-effort. Own session; never raises."""
    try:
        from database import SessionLocal
        from models.job_run import JobRun

        with SessionLocal() as session:
            session.add(
                JobRun(
                    name=name,
                    status=status,
                    duration_s=round(duration_s, 3),
                    error=(error or None) and (error or "")[:300],
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 — observability must never take down a job
        log.exception("job_runs: failed to record run for %s", name)


def run_logged(name: str, fn: Callable) -> Callable:
    """Wrap a scheduler job so every run lands a JobRun row.

    The wrapped callable preserves the job's exception behavior: an error is
    recorded AND re-raised so APScheduler still logs it."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            _record(name, "error", time.perf_counter() - start, repr(exc))
            raise
        _record(name, "ok", time.perf_counter() - start, None)
        return result

    return wrapper


def prune_job_runs(days: int = 14) -> int:
    """Delete JobRun rows older than `days`. Returns the count removed.
    Called from the nightly backup job; safe to call any time."""
    from sqlalchemy import delete

    from database import SessionLocal
    from models.job_run import JobRun

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with SessionLocal() as session:
        result = session.execute(delete(JobRun).where(JobRun.started_at < cutoff))
        session.commit()
        return int(result.rowcount or 0)
