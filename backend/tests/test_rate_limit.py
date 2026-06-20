"""Auth brute-force throttle (services/rate_limit) + the 429 it produces."""

from __future__ import annotations

from services.rate_limit import RateLimiter, auth_limiter


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
