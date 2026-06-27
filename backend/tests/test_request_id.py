"""Request-ID middleware (WS4 perf/ops).

Every response carries an `X-Request-ID`; an inbound one is honored so a
trace started at the edge keeps its id; the global rate-limit 429 (returned
by the inner middleware) still gets an id because the request-id layer is
outermost. Also smoke-checks the structured JSON log formatter.
"""

from __future__ import annotations

import json
import logging


def test_response_carries_generated_request_id(api_client):
    res = api_client.get("/health")
    rid = res.headers.get("X-Request-ID")
    assert rid, "every response must carry a generated X-Request-ID"
    # uuid4().hex is 32 hex chars.
    assert len(rid) == 32 and all(c in "0123456789abcdef" for c in rid)


def test_inbound_request_id_is_honored(api_client):
    res = api_client.get("/health", headers={"X-Request-ID": "trace-from-edge"})
    assert res.headers.get("X-Request-ID") == "trace-from-edge"


def test_request_ids_are_unique_per_request(api_client):
    a = api_client.get("/health").headers["X-Request-ID"]
    b = api_client.get("/health").headers["X-Request-ID"]
    assert a != b


def test_rate_limited_429_still_gets_request_id(api_client, monkeypatch):
    """The request-id layer is outermost, so even a 429 from the inner
    rate-limit middleware comes back with a correlation id."""
    from services.rate_limit import global_limiter

    monkeypatch.setattr(global_limiter, "max_attempts", 1)
    # Burn the budget on a non-exempt path, then trip the limiter.
    api_client.get("/api/market/status")
    res = None
    for _ in range(6):
        res = api_client.get("/api/market/status")
        if res.status_code == 429:
            break
    assert res is not None and res.status_code == 429
    assert res.headers.get("X-Request-ID"), "429 responses must still be traceable"


def test_json_formatter_emits_structured_fields():
    """The JSON formatter produces a parseable object with the stable key set
    and the bound request id."""
    from main import JsonFormatter, RequestIdFilter, request_id_ctx

    token = request_id_ctx.set("rid-123")
    try:
        record = logging.LogRecord(
            name="dashboard",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        RequestIdFilter().filter(record)
        line = JsonFormatter().format(record)
    finally:
        request_id_ctx.reset(token)

    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "dashboard"
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "rid-123"
    assert "timestamp" in payload
