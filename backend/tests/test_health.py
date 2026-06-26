"""/health liveness + DB-readiness probe (WS5 platform hardening).

Healthy → 200 with status "ok" and database "up". When the DB SELECT 1
fails (mocked — no real outage needed), /health reports "degraded" / "down"
and returns 503 so a load balancer pulls the box.
"""

from __future__ import annotations


def test_health_reports_db_up(api_client):
    res = api_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


def test_health_degraded_when_db_check_fails(api_client, monkeypatch):
    """Mock the engine so `SELECT 1` blows up; /health must degrade, not 500."""
    import database

    def _boom():
        raise RuntimeError("simulated DB outage")

    # The endpoint calls `engine.connect()`; make that raise.
    monkeypatch.setattr(database.engine, "connect", _boom)

    res = api_client.get("/health")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "degraded"
    assert body["database"] == "down"


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
