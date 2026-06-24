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

from fastapi import HTTPException, Request


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
    """

    def __init__(
        self,
        rate: float,
        capacity: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        self.rate = rate
        self.capacity = max(1.0, capacity)
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
        seconds actually slept (0 when a token was immediately available)."""
        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return 0.0
            deficit = tokens - self._tokens
            wait = deficit / self.rate
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
    # Honour the first hop of X-Forwarded-For when present (a reverse proxy
    # sets it); fall back to the socket peer. Good enough for throttling.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
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


# Module-level limiter shared by the auth endpoints. Configured from settings
# at import; tests reset it between cases via an autouse fixture.
def _build_auth_limiter() -> RateLimiter:
    from config import settings

    return RateLimiter(
        settings.auth_rate_limit_attempts, settings.auth_rate_limit_window_s
    )


auth_limiter = _build_auth_limiter()
