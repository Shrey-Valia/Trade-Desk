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
