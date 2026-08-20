"""/health must be able to see a DEAD SCHEDULER, not just a live process.

The failure this guards: the app answers HTTP perfectly, `SELECT 1` passes,
and the in-process APScheduler thread is dead — so billing renewals, combine
settlement, EOD settlement and the nightly backup have silently stopped
while every uptime check stays green. Liveness alone cannot see it; the only
external evidence is that nothing has written a JobRun row in a while.

These tests pin both directions: that real silence degrades to 503, and that
the two legitimate quiet periods do NOT (a fresh database with no rows, and
the startup grace window) — a health check that cries wolf gets muted, which
is worse than not having one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import main as main_mod
from config import settings
from models.job_run import JobRun


@pytest.fixture
def aged_process(monkeypatch):
    """Pretend the process has been up far longer than any window, so the
    startup grace never masks what a test is asserting."""
    monkeypatch.setattr(main_mod, "_PROCESS_STARTED_AT", 0.0)


def _add_run(session, *, seconds_ago: float) -> None:
    session.add(
        JobRun(
            name="monitor_orders",
            status="ok",
            duration_s=0.01,
            started_at=datetime.now(UTC) - timedelta(seconds=seconds_ago),
        )
    )
    session.commit()


# -- the alarm fires --------------------------------------------------------


def test_stale_scheduler_degrades_to_503(api_client, session_factory, aged_process):
    """Total silence past the window is the money-losing case: 503 so Fly
    restarts the machine and an uptime check actually pages someone."""
    with session_factory() as s:
        _add_run(s, seconds_ago=3600)

    res = api_client.get("/health")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["scheduler"] == "stale"
    # DB is fine — the scheduler is what's broken, and the body must say so.
    assert body["database"] == "up"


def test_recent_run_is_healthy(api_client, session_factory, aged_process):
    with session_factory() as s:
        _add_run(s, seconds_ago=5)

    res = api_client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "up", "scheduler": "ok"}


def test_boundary_just_inside_the_window(
    api_client, session_factory, aged_process, monkeypatch
):
    monkeypatch.setattr(settings, "health_scheduler_stale_s", 600)
    with session_factory() as s:
        _add_run(s, seconds_ago=590)
    assert api_client.get("/health").status_code == 200


# -- and does NOT cry wolf --------------------------------------------------


def test_empty_job_runs_is_unknown_not_stale(api_client, aged_process):
    """A fresh database has no rows. Reporting stale here would 503 every
    first boot and teach the operator to ignore the check."""
    res = api_client.get("/health")
    assert res.status_code == 200
    assert res.json()["scheduler"] == "unknown"


def test_startup_grace_masks_silence(api_client, session_factory, monkeypatch):
    """Inside one window of process start, silence means nothing yet — the
    scheduler may simply not have had time to run. Without this grace every
    restart would look like a dead scheduler."""
    monkeypatch.setattr(settings, "health_scheduler_stale_s", 600)
    # A very old run AND a process that just started.
    with session_factory() as s:
        _add_run(s, seconds_ago=99999)
    import time as _t

    monkeypatch.setattr(main_mod, "_PROCESS_STARTED_AT", _t.time())

    res = api_client.get("/health")
    assert res.status_code == 200
    assert res.json()["scheduler"] == "ok"


def test_check_can_be_disabled(api_client, session_factory, aged_process, monkeypatch):
    """An operator must be able to switch it off without patching code."""
    monkeypatch.setattr(settings, "health_scheduler_stale_s", 0)
    with session_factory() as s:
        _add_run(s, seconds_ago=99999)

    res = api_client.get("/health")
    assert res.status_code == 200
    assert res.json()["scheduler"] == "off"


# -- unauthenticated surface ------------------------------------------------


def test_health_leaks_no_job_detail(api_client, session_factory, aged_process):
    """/health is public. It may say "stale"; it must not name jobs, count
    them, or leak timings — that detail belongs behind the admin jobs view."""
    with session_factory() as s:
        _add_run(s, seconds_ago=3600)

    body = api_client.get("/health").json()
    assert set(body) == {"status", "database", "scheduler"}
    assert "monitor_orders" not in str(body)
