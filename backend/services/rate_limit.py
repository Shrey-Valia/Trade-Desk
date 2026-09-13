"""In-memory per-key rate limiting for auth endpoints.

A sliding-window counter keyed by "endpoint:client-ip": each call to
`hit()` drops timestamps older than the window and rejects once the
remaining count reaches the limit. Process-local and lock-guarded — fine
for a single-instance dev/prototype deployment; swap for Redis if this ever
runs multi-process.

The clock is injectable so the behaviour is unit-testable without sleeping.
Disabled entirely when the configured limit is <= 0.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException, Request

# Marks the current execution context as running on the BACKGROUND share of a
# split upstream budget (scheduled jobs: prewarm / watchlist refresh / chain
# collect). Request handlers never set it, so they draw from the reserved
# interactive bucket — warming can never starve a live trader. A ContextVar
# (not a plain global) so the flag follows a job across asyncio.to_thread's
# context copy and never leaks between concurrent requests.
_background_budget: ContextVar[bool] = ContextVar("background_budget", default=False)


@contextmanager
def background_budget():
    """Route upstream token-bucket takes inside this block to the background
    bucket (consulted by services.alpaca_client._spaced via
    `in_background_budget`)."""
    token = _background_budget.set(True)
    try:
        yield
    finally:
        _background_budget.reset(token)


def in_background_budget() -> bool:
    return _background_budget.get()


class RateLimiter:
    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_attempts > 0

    def hit(self, key: str) -> tuple[bool, float]:
        """Record an attempt for `key`. Returns (allowed, retry_after_secs).

        retry_after is 0 when allowed; otherwise the seconds until the
        oldest in-window hit expires and a slot frees up.
        """
        if not self.enabled:
            return True, 0.0
        now = self._clock()
        with self._lock:
            dq = self._hits[key]
            cutoff = now - self.window
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= self.max_attempts:
                retry_after = self.window - (now - dq[0])
                return False, max(0.0, retry_after)
            dq.append(now)
            return True, 0.0

    def reset(self) -> None:
        """Clear all counters (test helper / manual flush)."""
        with self._lock:
            self._hits.clear()


# Ceiling on how long a TokenBucket.take() will queue before giving up. Sized
# well above any legitimate wait — the market-data buckets bank a burst of 4-5
# tokens and refill at ~1/s, so a real fan-out settles in a few seconds — and
# well below the point where parked threads starve the request pool.
_DEFAULT_MAX_WAIT_S = 15.0


class TokenBucketExhausted(RuntimeError):
    """The bucket's queue is deeper than its max wait, so `take()` refused to
    join it. Callers translate this into their own degraded-upstream path
    (services.alpaca_client maps it to MarketDataUnavailable → 503)."""

    def __init__(self, wait_s: float) -> None:
        self.wait_s = wait_s
        super().__init__(
            f"upstream rate-limit queue is {wait_s:.1f}s deep — refusing to wait"
        )


class TokenBucket:
    """Token-bucket throttle for spacing out a SHARED upstream quota.

    Unlike RateLimiter (sliding window — rejects on overflow, used for
    auth brute-force), this one SMOOTHS bursts: `take()` blocks just long
    enough for a token to be available, so a fan-out of Alpaca calls on the
    single account key gets spread across time instead of bursting into a
    429. Capacity lets a short idle period bank a few tokens so a small
    burst still goes through immediately; sustained load settles to
    `rate` calls/sec.

    Clock + sleep are injectable so the spacing behaviour is unit-testable
    without real time.

    `max_wait_s` bounds the debt. Without it, sustained oversubscription grows
    the queue without limit: each caller drives `_tokens` further negative and
    `_updated` further into the future, so the computed wait keeps climbing.
    Because the callers are sync FastAPI handlers, every one of them parks an
    AnyIO threadpool thread while it sleeps — so an unbounded queue on the
    market-data bucket converts into thread exhaustion that stalls unrelated
    authenticated routes. Past the ceiling we raise `TokenBucketExhausted`
    instead of queueing, which callers translate into their existing
    degraded-feed path (a 503 + Retry-After) rather than a hung request.
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_wait_s: float = _DEFAULT_MAX_WAIT_S,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = rate
        self.capacity = max(1.0, capacity)
        self.max_wait_s = max_wait_s
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = self.capacity
        self._updated = clock()

    def _refill_locked(self) -> None:
        now = self._clock()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
            self._updated = now

    def take(self, tokens: float = 1.0) -> float:
        """Consume `tokens`, sleeping until they're available. Returns the
        seconds actually slept (0 when a token was immediately available).

        Raises TokenBucketExhausted when the queue is already deeper than
        `max_wait_s` — without consuming, so a rejected caller doesn't
        deepen the backlog for the ones still waiting."""
        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return 0.0
            deficit = tokens - self._tokens
            wait = deficit / self.rate
            if wait > self.max_wait_s:
                raise TokenBucketExhausted(wait)
            # Consume now; the sleep below pays for the debt so the NEXT
            # caller sees the bucket already drained (no double-spend).
            self._tokens -= tokens
            self._updated += wait
        self._sleep(wait)
        return wait

    def reset(self) -> None:
        with self._lock:
            self._tokens = self.capacity
            self._updated = self._clock()


def _client_ip(request: Request) -> str:
    """Best available client IP for throttle keying.

    X-Forwarded-For is CLIENT-CONTROLLED: with no trusted proxy in front, an
    attacker rotates the header on every request and lands each auth attempt
    under a fresh key — defeating the brute-force / global throttles entirely.
    So the header is honored ONLY when explicitly enabled (settings.trust_proxy
    — set it when the app really is behind a proxy that appends the real peer),
    and even then we take the RIGHT-most hop (the address the trusted proxy
    saw), not the left-most spoofable one. Otherwise the socket peer is used.
    """
    from config import settings

    if settings.trust_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            hops = [h.strip() for h in fwd.split(",") if h.strip()]
            if hops:
                return hops[-1]
    return request.client.host if request.client else "unknown"


def enforce(limiter: RateLimiter, request: Request, scope: str) -> None:
    """Raise 429 (with Retry-After) if `request`'s client has exceeded the
    limit for `scope`. No-op when the limiter is disabled."""
    allowed, retry_after = limiter.hit(f"{scope}:{_client_ip(request)}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="too many attempts — please wait and try again",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def enforce_user(limiter: RateLimiter, user_id: int, scope: str) -> None:
    """Per-USER variant of `enforce`: key by user_id + scope instead of client
    IP, for AUTHENTICATED financial actions (payout / activation / purchase).

    Keying by the signed-in user (not the socket IP) means one user behind a
    shared NAT/proxy can't exhaust another's budget, and a single user can't
    sidestep the limit by rotating IPs. Raises 429 (with Retry-After) on
    overflow; no-op when the limiter is disabled."""
    allowed, retry_after = limiter.hit(f"{scope}:user:{user_id}")
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="too many requests — please wait and try again",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


# Module-level limiter shared by the auth endpoints. Configured from settings
# at import; tests reset it between cases via an autouse fixture.
def _build_auth_limiter() -> RateLimiter:
    from config import settings

    return RateLimiter(
        settings.auth_rate_limit_attempts, settings.auth_rate_limit_window_s
    )


auth_limiter = _build_auth_limiter()


# Process-global per-IP limiter applied to EVERY request by the middleware
# in main.py (not just auth). Same sliding-window primitive as the auth
# limiter, just a coarser budget. Reset between tests like auth_limiter.
def _build_global_limiter() -> RateLimiter:
    from config import settings

    return RateLimiter(
        settings.global_rate_limit_attempts, settings.global_rate_limit_window_s
    )


global_limiter = _build_global_limiter()


# Per-USER limiter for the financial endpoints (payout / activation / purchase /
# checkout). Same sliding-window primitive, keyed by user_id+scope via
# enforce_user. Tight budget; reset between tests like the others.
def _build_financial_limiter() -> RateLimiter:
    from config import settings

    return RateLimiter(
        settings.financial_rate_limit_attempts, settings.financial_rate_limit_window_s
    )


financial_limiter = _build_financial_limiter()
