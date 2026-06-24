"""Circuit breaker + backoff (services/resilience)."""

from __future__ import annotations

import pytest

from services.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    breaker_retry_after,
    get_breaker,
    reset_breakers,
    resilient_call,
)


@pytest.fixture(autouse=True)
def _clean_breakers():
    """Process-wide breaker registry — clear it around each test."""
    reset_breakers()
    yield
    reset_breakers()


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_breaker_opens_after_threshold_and_blocks():
    clk = FakeClock()
    b = CircuitBreaker("x", fail_threshold=3, cooldown=30.0, clock=clk)
    assert b.allow()
    b.record_failure()
    b.record_failure()
    assert b.allow()  # 2 < 3, still closed
    b.record_failure()  # 3rd → open
    assert b.is_open
    assert not b.allow()


def test_breaker_half_opens_after_cooldown_then_closes_on_success():
    clk = FakeClock()
    b = CircuitBreaker("x", fail_threshold=1, cooldown=30.0, clock=clk)
    b.record_failure()
    assert not b.allow()
    clk.advance(29.0)
    assert not b.allow()  # still cooling
    clk.advance(2.0)
    assert b.allow()  # half-open probe permitted
    b.record_success()
    assert b.allow() and not b.is_open  # closed


def test_breaker_reopens_on_half_open_failure():
    clk = FakeClock()
    b = CircuitBreaker("x", fail_threshold=1, cooldown=10.0, clock=clk)
    b.record_failure()
    clk.advance(11.0)
    assert b.allow()  # half-open
    b.record_failure()  # probe failed → reopen, timer resets
    assert not b.allow()


def test_record_success_resets_fail_count():
    b = CircuitBreaker("x", fail_threshold=3, cooldown=30.0, clock=FakeClock())
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    b.record_failure()
    assert b.allow()  # only 2 since reset → still closed


def test_resilient_call_short_circuits_when_open():
    clk = FakeClock()
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("429 too many requests")

    # fail_threshold=1 so the first failure opens it.
    for _ in range(1):
        with pytest.raises(RuntimeError):
            resilient_call(
                "rl", boom, retries=0, sleep=lambda _: None,
                breaker_kwargs={"fail_threshold": 1, "cooldown": 60.0, "clock": clk},
            )
    # Now open → next call short-circuits WITHOUT invoking fn.
    before = calls["n"]
    with pytest.raises(CircuitOpenError):
        resilient_call("rl", boom, retries=0, sleep=lambda _: None)
    assert calls["n"] == before  # fn not called


def test_rate_limit_is_not_retried():
    calls = {"n": 0}

    def rl():
        calls["n"] += 1
        raise RuntimeError("Too Many Requests")

    with pytest.raises(RuntimeError):
        resilient_call(
            "rl2", rl, retries=3, sleep=lambda _: None,
            breaker_kwargs={"fail_threshold": 99},
        )
    assert calls["n"] == 1  # no retries on a rate-limit error


def test_transient_error_is_retried_then_raises():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        raise TimeoutError("connection timed out")

    with pytest.raises(TimeoutError):
        resilient_call(
            "tr", flaky, retries=2, sleep=lambda _: None,
            breaker_kwargs={"fail_threshold": 99},
        )
    assert calls["n"] == 3  # initial + 2 retries


def test_succeeds_after_one_transient_retry():
    calls = {"n": 0}

    def recover():
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("transient")
        return "ok"

    out = resilient_call(
        "rec", recover, retries=2, sleep=lambda _: None,
        breaker_kwargs={"fail_threshold": 99},
    )
    assert out == "ok"
    assert calls["n"] == 2


# -- retry-after / degraded response -----------------------------------------


def test_retry_after_reflects_remaining_cooldown():
    clk = FakeClock()
    b = CircuitBreaker("ra", fail_threshold=1, cooldown=30.0, clock=clk)
    assert b.retry_after() == 0.0  # closed → may call now
    b.record_failure()             # opens at t=0
    assert b.retry_after() == 30.0
    clk.advance(20.0)
    assert b.retry_after() == 10.0
    clk.advance(15.0)              # past cooldown → half-open
    assert b.retry_after() == 0.0


def test_breaker_retry_after_helper_rounds_up_and_defaults():
    # Unknown breaker → the supplied default (whole seconds).
    assert breaker_retry_after("does-not-exist", default=42) == 42

    clk = FakeClock()
    b = get_breaker("known", fail_threshold=1, cooldown=30.0, clock=clk)
    b.record_failure()  # opens
    clk.advance(0.4)
    # 29.6s remaining → rounds UP to 30, and is never 0 (would re-trip).
    assert breaker_retry_after("known") == 30


def test_chart_endpoint_returns_typed_503_when_circuit_open(api_client, monkeypatch):
    """A circuit-open / degraded feed yields a typed 503 (Retry-After +
    {"error": "market_data_unavailable"} body) — NOT a bare 500 or a 404
    — so the frontend can render a retrying state instead of a spinner."""
    from services.alpaca_client import MarketDataUnavailable
    import routers.ticker as ticker

    def _degraded(symbol, timeframe):
        raise MarketDataUnavailable(f"{symbol} circuit open")

    monkeypatch.setattr(ticker, "get_bars", _degraded)

    res = api_client.get("/api/ticker/SPY/bars?timeframe=5m")
    assert res.status_code == 503
    assert "Retry-After" in res.headers
    assert int(res.headers["Retry-After"]) >= 1
    body = res.json()
    assert body["error"] == "market_data_unavailable"
    assert "retry_after" in body

    # The full /chart endpoint degrades the same way (bars are its first leg).
    res2 = api_client.get("/api/ticker/SPY/chart?timeframe=5m")
    assert res2.status_code == 503
    assert res2.json()["error"] == "market_data_unavailable"
