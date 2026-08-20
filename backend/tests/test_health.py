"""/health liveness + DB-readiness probe (WS5 platform hardening).

Healthy → 200 with status "ok" and database "up". When the DB SELECT 1
fails (mocked — no real outage needed), /health reports "degraded" / "down"
and returns 503 so a load balancer pulls the box.

Scheduler liveness lives in test_health_scheduler.py; the outage case below
also pins that a DB outage is NOT misreported as a dead scheduler.
"""

from __future__ import annotations


def test_health_reports_db_up(api_client):
    res = api_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


def test_health_degraded_when_db_check_fails(api_client, monkeypatch):
    """A session whose every query raises; /health must degrade, not 500.

    Mocks the INJECTED SESSION rather than `engine.connect()`: /health now
    takes its session from the get_session dependency and reuses it for both
    the SELECT 1 and the scheduler-staleness read, so that dependency is the
    honest seam for "the database is unreachable".
    """
    import main as main_mod
    from database import get_session
    from main import app

    # Age the process past the staleness window, or the scheduler check
    # short-circuits to "ok" inside its startup grace and never reaches the
    # (failing) read this test is about.
    monkeypatch.setattr(main_mod, "_PROCESS_STARTED_AT", 0.0)

    class _DeadSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("simulated DB outage")

    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = lambda: _DeadSession()
    try:
        res = api_client.get("/health")
    finally:
        if previous is not None:
            app.dependency_overrides[get_session] = previous
        else:
            app.dependency_overrides.pop(get_session, None)

    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["database"] == "down"
    # An unreachable DB must not masquerade as a dead scheduler — the
    # staleness read failed too, and "unknown" is the honest answer.
    assert body["scheduler"] == "unknown"


def test_health_exempt_from_global_rate_limit(api_client, monkeypatch):
    """Probes must never 429 even when the global limiter is exhausted —
    otherwise an LB marks the box unhealthy and pulls it."""
    from services.rate_limit import global_limiter

    monkeypatch.setattr(global_limiter, "max_attempts", 1)
    # Burn the budget on a normal path, then hammer /health.
    api_client.get("/health")
    for _ in range(5):
        res = api_client.get("/health")
        assert res.status_code == 200
