"""Scheduled-job run records — observability for the APScheduler fleet.

One row per run of each money-critical job (settle_combines, renew_combines,
monitor_orders, …) written by services/job_runs.run_logged. If settle_combines
silently stops, payouts freeze and funded terminations stop enforcing — the
admin jobs-health endpoint reads the latest row per job so a stalled or
failing job is visible instead of a matter of tailing logs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, UTCDateTime


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        # Health query: latest run per job name.
        Index("ix_job_runs_name_started", "name", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    # "ok" | "error"
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
