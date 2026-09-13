"""Auth brute-force throttle (services/rate_limit) + the 429 it produces."""

from __future__ import annotations

import pytest

from services.rate_limit import (
    RateLimiter,
    TokenBucket,
    TokenBucketExhausted,
    auth_limiter,
    global_limiter,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_allows_up_to_limit_then_blocks():
    rl = RateLimiter(3, 60, clock=FakeClock())
    assert rl.hit("k")[0]
    assert rl.hit("k")[0]
    assert rl.hit("k")[0]
    allowed, retry_after = rl.hit("k")
    assert not allowed
    assert retry_after > 0


def test_window_expiry_frees_slots():
    clk = FakeClock()
    rl = RateLimiter(2, 60, clock=clk)
    assert rl.hit("k")[0]
    assert rl.hit("k")[0]
    assert not rl.hit("k")[0]
    clk.advance(61)  # both hits aged out
    assert rl.hit("k")[0]


def test_keys_are_independent():
    rl = RateLimiter(1, 60, clock=FakeClock())
    assert rl.hit("a")[0]
    assert not rl.hit("a")[0]
    assert rl.hit("b")[0]  # different key unaffected


def test_disabled_when_limit_non_positive():
    rl = RateLimiter(0, 60, clock=FakeClock())
    assert not rl.enabled
    for _ in range(100):
        assert rl.hit("k")[0]  # never blocks


def test_reset_clears_counters():
    rl = RateLimiter(1, 60, clock=FakeClock())
    rl.hit("k")
    assert not rl.hit("k")[0]
    rl.reset()
    assert rl.hit("k")[0]


# -- TokenBucket (Alpaca call-spacing throttle) ------------------------------


class FakeSleeper:
    """Records requested sleeps and ADVANCES the fake clock by that much,
    so token refill behaves as if real time passed — without real sleeping."""

    def __init__(self, clock: "FakeClock") -> None:
        self.clock = clock
        self.slept: list[float] = []

    def __call__(self, secs: float) -> None:
        self.slept.append(secs)
        self.clock.advance(secs)


def test_token_bucket_lets_burst_through_up_to_capacity():
    clk = FakeClock()
    sleeper = FakeSleeper(clk)
    tb = TokenBucket(rate=5.0, capacity=3.0, clock=clk, sleep=sleeper)
    # 3 tokens banked → first 3 takes are immediate (no sleep).
    assert tb.take() == 0.0
    assert tb.take() == 0.0
    assert tb.take() == 0.0
    assert sleeper.slept == []


def test_token_bucket_spaces_calls_once_drained():
    clk = FakeClock()
    sleeper = FakeSleeper(clk)
    tb = TokenBucket(rate=5.0, capacity=1.0, clock=clk, sleep=sleeper)
    assert tb.take() == 0.0          # consumes the one banked token
    waited = tb.take()               # must wait 1/5s for the next token
    assert waited == pytest.approx(0.2, abs=1e-9)
    assert sleeper.slept == [pytest.approx(0.2, abs=1e-9)]


def test_token_bucket_refills_over_time():
    clk = FakeClock()
    sleeper = FakeSleeper(clk)
    tb = TokenBucket(rate=10.0, capacity=2.0, clock=clk, sleep=sleeper)
    tb.take()
    tb.take()                        # bucket drained
    clk.advance(1.0)                 # 1s → +10 tokens, capped at capacity=2
    assert tb.take() == 0.0
    assert tb.take() == 0.0          # both refilled tokens available immediately
    assert tb.take() > 0.0           # third must wait again


def test_token_bucket_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        TokenBucket(rate=0.0, capacity=1.0)


def test_token_bucket_waits_normally_below_the_ceiling():
    """The ceiling must not disturb ordinary spacing — a wait under the cap
    still sleeps and still returns the slept duration."""
    clk = FakeClock()
    sleeper = FakeSleeper(clk)
    tb = TokenBucket(rate=5.0, capacity=1.0, clock=clk, sleep=sleeper, max_wait_s=10.0)
    assert tb.take() == 0.0
    assert tb.take() == pytest.approx(0.2, abs=1e-9)
    assert sleeper.slept == [pytest.approx(0.2, abs=1e-9)]


class StuckSleeper:
    """Records sleeps WITHOUT advancing the clock.

    This is what oversubscription actually looks like: many threads queue on
    the bucket at effectively the same instant, so wall-clock time does not
    advance enough to repay the debt between takes. FakeSleeper would refill
    the bucket on every sleep and the backlog could never build."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    def __call__(self, secs: float) -> None:
        self.slept.append(secs)


def test_token_bucket_refuses_to_queue_past_the_ceiling():
    """Sustained oversubscription used to grow the wait without bound while
    each caller parked a threadpool thread. Past the cap, take() raises
    instead of joining the queue."""
    sleeper = StuckSleeper()
    tb = TokenBucket(
        rate=1.0, capacity=1.0, clock=FakeClock(), sleep=sleeper, max_wait_s=2.0
    )
    assert tb.take() == 0.0                            # the one banked token
    assert tb.take() == pytest.approx(1.0, abs=1e-9)   # 1s debt — under the cap
    assert tb.take() == pytest.approx(2.0, abs=1e-9)   # 2s — exactly at the cap
    with pytest.raises(TokenBucketExhausted):          # 3s — over it
        tb.take()


def test_token_bucket_rejection_does_not_deepen_the_queue():
    """A refused caller must not consume — otherwise every rejection makes
    the wait worse for the callers still legitimately queued."""
    sleeper = StuckSleeper()
    tb = TokenBucket(
        rate=1.0, capacity=1.0, clock=FakeClock(), sleep=sleeper, max_wait_s=1.0
    )
    tb.take()                        # banked token
    tb.take()                        # 1s debt — at the cap
    with pytest.raises(TokenBucketExhausted):
        tb.take()
    before = tb._tokens
    with pytest.raises(TokenBucketExhausted):
        tb.take()
    assert tb._tokens == before      # the rejection cost nothing
    assert sleeper.slept == [pytest.approx(1.0, abs=1e-9)]  # rejections never slept


def test_token_bucket_exhausted_reports_the_wait_it_refused():
    sleeper = StuckSleeper()
    tb = TokenBucket(
        rate=1.0, capacity=1.0, clock=FakeClock(), sleep=sleeper, max_wait_s=1.0
    )
    tb.take()
    tb.take()
    with pytest.raises(TokenBucketExhausted) as exc:
        tb.take()
    assert exc.value.wait_s == pytest.approx(2.0, abs=1e-9)


def test_signin_throttled_returns_429(api_client, monkeypatch):
    monkeypatch.setattr(auth_limiter, "max_attempts", 2)
    body = {"email": "nobody@test.local", "password": "wrongpass"}
    assert api_client.post("/api/auth/signin", json=body).status_code == 401
    assert api_client.post("/api/auth/signin", json=body).status_code == 401
    res = api_client.post("/api/auth/signin", json=body)  # 3rd → blocked
    assert res.status_code == 429
    assert "Retry-After" in res.headers


def test_signin_and_signup_have_separate_budgets(api_client, monkeypatch):
    monkeypatch.setattr(auth_limiter, "max_attempts", 1)
    # Exhaust the signin budget.
    api_client.post("/api/auth/signin", json={"email": "x@test.local", "password": "y"})
    assert (
        api_client.post(
            "/api/auth/signin", json={"email": "x@test.local", "password": "y"}
        ).status_code
        == 429
    )
    # Signup still has its own budget (different scope) — first call goes
    # through (201), not pre-empted by the signin throttle.
    res = api_client.post(
        "/api/auth/signup",
        json={"email": "fresh@test.local", "password": "password123"},
    )
    assert res.status_code == 201


# -- Global per-IP throttle (main.py middleware) -----------------------------


def test_global_limiter_blocks_after_limit(api_client, monkeypatch):
    """The global middleware 429s ANY endpoint once the per-IP budget is
    spent — here on a non-auth path so it's clearly the global limiter, not
    the auth one. Returns a Retry-After header."""
    monkeypatch.setattr(global_limiter, "max_attempts", 3)
    # A cheap, always-present non-auth route.
    path = "/api/watchlist"
    assert api_client.get(path).status_code != 429
    assert api_client.get(path).status_code != 429
    assert api_client.get(path).status_code != 429
    res = api_client.get(path)  # 4th request → throttled
    assert res.status_code == 429
    assert "Retry-After" in res.headers
    assert res.json()["detail"]


def test_global_limiter_disabled_when_attempts_non_positive(api_client, monkeypatch):
    """attempts <= 0 disables the global throttle entirely (e.g. behind an
    upstream limiter) — many requests, never a 429."""
    monkeypatch.setattr(global_limiter, "max_attempts", 0)
    assert not global_limiter.enabled
    for _ in range(50):
        assert api_client.get("/api/watchlist").status_code != 429


def test_global_limiter_independent_of_auth_budget(api_client, monkeypatch):
    """The global throttle and the auth brute-force throttle are separate
    budgets: exhausting auth signin attempts doesn't pre-empt a non-auth
    request through the global limiter, and vice-versa."""
    monkeypatch.setattr(auth_limiter, "max_attempts", 1)
    monkeypatch.setattr(global_limiter, "max_attempts", 100)
    # Burn the auth signin budget → 429 from the auth limiter.
    api_client.post("/api/auth/signin", json={"email": "a@b.c", "password": "x"})
    assert (
        api_client.post(
            "/api/auth/signin", json={"email": "a@b.c", "password": "x"}
        ).status_code
        == 429
    )
    # A non-auth path still flows: global budget is large, untouched by auth.
    assert api_client.get("/api/watchlist").status_code != 429
